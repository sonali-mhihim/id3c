"""
Routes for identifier minting.
"""
import logging
from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest, NotFound
from .. import datastore
from ..utils.routes import authentication_required, content_types_accepted, check_content_length


LOG = logging.getLogger(__name__)

blueprint = Blueprint("identifier-sets", __name__)


@blueprint.route("/identifier-sets", methods = ['GET'])
@authentication_required
def get_sets():
    """
    Retrieve metadata about all identifier sets.

    GET /identifier-set to receive a JSON array of objects, each containing a
    set's metadata fields.
    """
    session = datastore.login(
        username = request.authorization.username,
        password = request.authorization.password)

    LOG.debug(f"Fetching identifier sets")

    sets = datastore.fetch_identifier_sets(session)

    return jsonify([ set._asdict() for set in sets ])


@blueprint.route("/identifier-sets/<name>", methods = ['GET'])
@authentication_required
def get_set(name):
    """
    Retrieve an identifier set's metadata.

    GET /identifier-set/*name* to receive a JSON object containing the set's
    metadata fields.
    """
    session = datastore.login(
        username = request.authorization.username,
        password = request.authorization.password)

    LOG.debug(f"Fetching identifier set «{name}»")

    set = datastore.fetch_identifier_set(session, name)

    return jsonify(set._asdict())


@blueprint.route("/identifier-sets/<name>", methods = ['PUT'])
@authentication_required
def put_set(name):
    """
    Make a new identifier set.

    PUT /identifier-sets/*name* to create the set if it doesn't yet exist.  201
    Created is returned when the set is created, 204 No Content if the set
    already existed.
    """
    session = datastore.login(
        username = request.authorization.username,
        password = request.authorization.password)

    LOG.debug(f"Making identifier set «{name}»")

    new_set = datastore.make_identifier_set(session, name)

    return "", 201 if new_set else 204


@blueprint.route("/identifier-sets/<name>/identifiers", methods = ['POST'])
@content_types_accepted(["application/x-www-form-urlencoded", "multipart/form-data"])
@check_content_length
@authentication_required
def mint_in_set(name):
    """
    Mint *n* new identifiers in the set *name*.

    POST /identifier-sets/*name*/identifiers with an *n* form parameter
    specifying how many new identifiers you'd like to mint.  Responds with a
    JSON array of objects (the new identifiers) containing the keys ``uuid``,
    ``barcode``, and ``generated``.

    This may take some time with a large *n* or with a lot of existing
    identifiers.
    """
    session = datastore.login(
        username = request.authorization.username,
        password = request.authorization.password)

    try:
        n = int(request.form['n'])
    except ValueError as error:
        raise BadRequest("n must be a plain integer")

    LOG.debug(f"Minting {n} new identifiers in set «{name}»")

    minted = datastore.mint_identifiers(session, name, n)

    return jsonify([ identifier._asdict() for identifier in minted ])
