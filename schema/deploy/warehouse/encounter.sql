-- Deploy seattleflu/schema:warehouse/encounter to pg
-- requires: warehouse/individual
-- requires: warehouse/site

begin;

set search_path to warehouse;

create table encounter (
    encounter_id integer primary key generated by default as identity,
    identifier text not null unique,

    -- Who
    individual_id integer references individual (individual_id) not null,

    -- Where
    site_id integer references site (site_id) not null,

    -- When
    encountered timestamp with time zone not null,

    details jsonb
);

comment on table encounter is 'An interaction with an individual to collect point-in-time information or samples';
comment on column encounter.encounter_id is 'Internal id of this encounter';
comment on column encounter.identifier is 'External identifier for this encounter; case-sensitive';
comment on column encounter.individual_id is 'Who was encountered';
comment on column encounter.site_id is 'Where the encounter occurred';
comment on column encounter.encountered is 'When the encounter occurred';
comment on column encounter.details is 'Additional information about this encounter which does not have a place in the relational schema';

create index encounter_individual_id_idx on encounter (individual_id);
create index encounter_site_id_idx on encounter (site_id);
create index encounter_encountered_id_idx on encounter (encountered);
create index encounter_details_idx on encounter using gin (details jsonb_path_ops);

commit;
