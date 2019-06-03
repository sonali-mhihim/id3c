-- Deploy seattleflu/schema:receiving/manifest to pg
-- requires: receiving/schema

begin;

set local search_path to receiving;

create table manifest (
    manifest_id integer primary key generated by default as identity,

    -- Using json not jsonb because we want to keep the exact text around for
    -- debugging purposes.
    document json not null
        constraint manifest_document_is_object
            check (json_typeof(document) = 'object'),

    received timestamp with time zone not null default now(),

    processing_log jsonb not null default '[]'
        constraint manifest_processing_log_is_array
            check (jsonb_typeof(processing_log) = 'array')
);

comment on table manifest is
    'Append-only set of sample manifest records';

comment on column manifest.manifest_id is
    'Internal id of this record';

comment on column manifest.document is
    'Record as a JSON document';

comment on column manifest.received is
    'When the document was received';

comment on column manifest.processing_log is
    'Event log recording details of ETL into the warehouse';

commit;
