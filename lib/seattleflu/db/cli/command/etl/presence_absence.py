"""
Process presence-absence tests into the relational warehouse

The ETL process performs a `find_or_create` for targets, as we anticipate the same targets to be tested, but leave room for the addition of new targets.

The ETL process performs a `find_or_create` for samples to allow the processing of re-tested samples. We do not expect to update information of a sample itself.

The ETL process performs an `upsert` for presence_absence to allow the update of results should there be a re-test on an old sample.

The presence-absence ETL process will abort under these conditions:

1. If a sample's barcode matches with a UUID that is of the incorrect identifier set

2. If we receive an unexpected value for the "controlStatus" of a target

3. If we receive an unexpected value for the "targetResult" of a specific test
"""
import click
import logging
from datetime import datetime, timezone
from typing import Any
from seattleflu.db.session import DatabaseSession
from seattleflu.db.datatypes import Json
from . import etl


LOG = logging.getLogger(__name__)


# This revision number is stored in the processing_log of each presence-absence
# record when the presence-absence test is successfully processed by this ETL 
# routine. The routine finds new-to-it records to process by looking for
# presence-absence tests lacking this revision number in their log.  If a 
# change to the ETL routine necessitates re-processing all presence-absence tests, 
# this revision number should be incremented.
REVISION = 1


@etl.command("presence-absence", help = __doc__)

@click.option("--dry-run", "action",
    help        = "Only go through the motions of changing the database (default)",
    flag_value  = "rollback",
    default     = True)

@click.option("--prompt", "action",
    help        = "Ask if changes to the database should be saved",
    flag_value  = "prompt")

@click.option("--commit", "action",
    help        = "Save changes to the database",
    flag_value  = "commit")

def etl_presence_absence(*, action: str):
    LOG.debug(f"Starting the presence_absence ETL routine, revision {REVISION}")

    db = DatabaseSession()

    # Fetch and iterate over presence-absence tests that aren't processed
    #
    # Rows we fetch are locked for update so that two instances of this
    # command don't try to process the same presence-absence tests.
    LOG.debug("Fetching unprocessed presence-absence tests")

    presence_absence = db.cursor("presence_absence")
    presence_absence.execute("""
        select presence_absence_id as id, document
          from receiving.presence_absence
         where not processing_log @> %s
         order by id
           for update
        """, (Json([{ "revision": REVISION }]),))

    processed_without_error = None

    try:
        for group in presence_absence:
            with db.savepoint(f"presence_absence group {group.id}"):
                LOG.info(f"Processing presence_absence group {group.id}")

                # I'm not sure why, but there are two kinds of documents we get
                # from Samplify: initial data pushes and updates.  Both use the
                # same internal structure, but the outer container varies.
                # This sort of thing should go away when we can convince
                # Samplify to send us data in a format we'd prefer.
                #   -trs, 17 May 2019
                try:
                    received_samples = group.document["store"]["items"]
                except KeyError:
                    received_samples = group.document["Update"]

                for received_sample in received_samples:
                    received_sample_id = received_sample["investigatorId"]
                    LOG.info(f"Processing sample «{received_sample_id}»")

                    # Eventually, we will want to convert the external identifier
                    # (e.g. barcode) to the original uuid.
                    sample = find_or_create_sample(db,
                        identifier  = sample_identifier(db, received_sample_id), 
                        details = sample_details(received_sample))

                    for test_result in received_sample["targetResults"]:
                        test_result_target_id = test_result["geneTarget"]
                        LOG.debug(f"Processing target «{test_result_target_id}» for \
                        sample «{received_sample_id}»")
                        
                        # Most of the time we expect to see existing targets so a
                        # select-first approach makes the most sense to avoid useless
                        # updates.
                        target = find_or_create_target(db,
                            identifier = test_result_target_id,
                            control = target_control(test_result["controlStatus"]))

                        # Most of the time we expect to see new samples and new
                        # presence_absence tests, so an insert-first approach makes more sense.
                        # Presence-absence tests we see more than once are presumed to be
                        # corrections.
                        upsert_presence_absence(db,
                            identifier = test_result["id"],
                            sample_id  = sample.id,
                            target_id  = target.id,
                            present    = get_target_result(test_result["targetStatus"]),
                            details = presence_absence_details(test_result))

                mark_processed(db, group.id)

                LOG.info(f"Finished processing presence_absence group {group.id}")

    except Exception as error:
        processed_without_error = False

        LOG.error(f"Aborting with error")
        raise error from None

    else:
        processed_without_error = True

    finally:
        if action == "prompt":
            ask_to_commit = \
                "Commit all changes?" if processed_without_error else \
                "Commit successfully processed presence-absence tests up to this point?"

            commit = click.confirm(ask_to_commit)
        else:
            commit = action == "commit"

        if commit:
            LOG.info(
                "Committing all changes" if processed_without_error else \
                "Committing successfully processed presence-absence tests up to this point")
            db.commit()

        else:
            LOG.info("Rolling back all changes; the database will not be modified")
            db.rollback()

def find_or_create_target(db: DatabaseSession, identifier: str, control: bool) -> Any:
    """
    Select presence_absence test target by *identifier*, or insert it if it doesn't exist.
    """
    LOG.debug(f"Looking up target «{identifier}»")

    target = db.fetch_row("""
        select target_id as id, identifier
          from warehouse.target
         where identifier = %s
        """, (identifier,))

    if target:
        LOG.info(f"Found target {target.id} «{target.identifier}»")
    else:
        LOG.debug(f"Target «{identifier}» not found, adding")

        data = {
            "identifier": identifier,
            "control": control
        }

        target = db.fetch_row("""
            insert into warehouse.target (identifier, control)
                values (%(identifier)s, %(control)s)
            returning target_id as id, identifier
            """, data)

        LOG.info(f"Created target {target.id} «{target.identifier}»")

    return target


def target_control(control: str) -> bool:
    """
    Determine the control status of the target.
    """
    expected_values = ["NotControl", "PositiveControl"]
    if not control or control not in expected_values: 
        raise UnknownControlStatusError(f"Unknown control status «{control}».")
    return control == "PositiveControl"


def find_or_create_sample(db: DatabaseSession, identifier: str,
                          details: dict) -> Any:
    """
    Select sample by *identifier*, or insert it if it doesn't exist.

    TODO: find sample and error if it is not found. Do not create new samples.
    """
    LOG.debug(f"Looking up sample «{identifier}»")

    sample = db.fetch_row("""
        select sample_id as id, identifier
          from warehouse.sample
         where identifier = %s
        """, (identifier,))

    if sample:
        LOG.info(f"Found sample {sample.id} «{sample.identifier}»")
    else:
        LOG.debug(f"Sample «{identifier}» not found, adding")

        data = {
            "identifier": identifier,
            "details": Json(details)
        }

        sample = db.fetch_row("""
            insert into warehouse.sample (
                identifier, 
                details)
                
                values (
                    %(identifier)s, 
                    %(details)s)
                    
            returning sample_id as id, identifier
            """, data)

        LOG.info(f"Created sample {sample.id} «{sample.identifier}»")

    return sample

def sample_identifier(db: DatabaseSession, barcode: str) -> str:
    """
    Find corresponding UUID for scanned sample barcode within
    warehouse.identifier.
    
    TODO determine course of action if barcode not found
    within warehouse.identifier.
    """

    LOG.debug(f"Looking up sample barcode {barcode} to find UUID")

    uuid = db.fetch_row("""
        select uuid, name
          from warehouse.identifier
          join warehouse.identifier_set using (identifier_set_id)
         where barcode = %s
        """, (barcode,))
    if uuid:
        #Check Identifier_Set
        if uuid.name == "samples":
            LOG.info(f"Found sample UUID {uuid.uuid}")
            return uuid.uuid
        else:
            raise IncorrectIdentifierSetError(f"Found sample UUID {uuid.uuid}, \
                but UUID is of the incorrect identifier set «{uuid.name}»")
    else:
        LOG.warning(f"No corresponding UUID found for barcode «{barcode}»")
        return barcode


def sample_details(document: dict) -> dict:
    """
    Describe sample details in a simple data structure designed to be used
    from SQL.
    """
    return { 
        "sample_comment": document['sampleComment'],
        "initial_sequencing_call": document['initialProceedToSequencingCall'],
        "final_sequencing_call": document["sampleProceedToSequencing"]
    }

def presence_absence_details(document: dict) -> dict:
    """
    Describe presence/absence details in a simple data structure designed to
    be used from SQL.
    """
    return {
        "replicates": document['wellResults']
    }

def upsert_presence_absence(db: DatabaseSession,
                            identifier: str,
                            sample_id: int,
                            target_id: int,
                            present: bool,
                            details: dict) -> Any:
    """
    Upsert presence_absence by its *identifier*.

    Confirmed with Samplify that their numeric identifier for each test is stable 
    and persistent.
    """
    LOG.debug(f"Upserting presence_absence «{identifier}»")

    data = {
        "identifier": f"NWGC_{identifier}",
        "sample_id": sample_id,
        "target_id": target_id,
        "present": present,
        "details": Json(details)
    }

    presence_absence = db.fetch_row("""
        insert into warehouse.presence_absence (
                identifier,
                sample_id,
                target_id,
                present,
                details)
            values (
                %(identifier)s,
                %(sample_id)s,
                %(target_id)s,
                %(present)s,
                %(details)s)

        on conflict (identifier) do update
            set sample_id = excluded.sample_id,
                target_id = excluded.target_id,
                present   = excluded.present,
                details = excluded.details

        returning presence_absence_id as id, identifier
        """, data)

    assert presence_absence.id, "Upsert affected no rows!"

    LOG.info(f"Upserted presence_absence {presence_absence.id} \
        «{presence_absence.identifier}»")

    return presence_absence


def get_target_result(target_status: str) -> Any:
    """
    Takes a given target status and its sample and target ids. Returns the decoded 
    target_result as a boolean if the given target status is known. If the given
    target status is an unexpected value, error will be raised and the ETL process will abort. 
    """
    expected_values = ['Detected', 'NotDetected']

    if not target_status or target_status not in expected_values:
        raise UnknownTargetResultError(f"Unknown target result «{target_status}».")

    return target_status == 'Detected'


def mark_processed(db, group_id: int) -> None:
    LOG.debug(f"Marking presence_absence group {group_id} as processed")

    data = {
        "group_id": group_id,
        "log_entry": Json({
            "revision": REVISION,
            "timestamp": datetime.now(timezone.utc),
        }),
    }

    with db.cursor() as cursor:
        cursor.execute("""
            update receiving.presence_absence
               set processing_log = processing_log || %(log_entry)s
             where presence_absence_id = %(group_id)s
            """, data)

class IncorrectIdentifierSetError(ValueError):
    """
    Raised by :function:`sample_identifier` if its provided *barcode* 
    matches a UUID that is of the incorrect identifier set.
    """
    pass

class UnknownControlStatusError(ValueError):
    """
    Raised by :function:`target_control` if its provided *control*
    is not amont the set of expected values.
    """
    pass

class UnknownTargetResultError(ValueError):
    """
    Raised by :function:`get_target_result` if its provided *target_result* 
    is not among the set of expected values.
    """
    pass
