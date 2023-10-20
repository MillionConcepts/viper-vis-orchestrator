"""base classes to help glue Django forms to SQLAlchemy."""
from collections import defaultdict
from functools import cached_property
from typing import Union, Mapping, Callable, Optional

from cytoolz import keyfilter
from django import forms
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound, InvalidRequestError
from sqlalchemy.orm import Session

from func import get_argnames
from viper_orchestrator.db.session import autosession
from viper_orchestrator.db.table_utils import sa_attached_to

from viper_orchestrator.visintent.tracking.tables import ProtectedListEntry
from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.image_requests import ImageRequest
from vipersci.vis.db.junc_image_record_tags import JuncImageRecordTag
from vipersci.vis.db.junc_image_req_ldst import JuncImageRequestLDST

AppTable = Union[ImageRequest, ImageRecord, ProtectedListEntry]
JuncTable = Union[JuncImageRecordTag, JuncImageRequestLDST]
AssociationRule = Mapping[
    str, Union[str, JuncTable, tuple[str], Callable[[], None]]
]


class SAForm(forms.Form):
    """abstract-ish class for forms that help manage SQLAlchemy ORM objects"""

    def get_row(
        self,
        session: Optional[Session] = None,
        force_remake: bool = False,
        constructor_method: Optional[str] = None
    ) -> AppTable:
        if (
            (self._row is not None)
            and sa_attached_to(self._row, session)
            and (force_remake is False)
        ):
            return self._row
        data = {k: v for k, v in self.cleaned_data.items()}
        data |= {attr: getattr(self, attr) for attr in self.extra_attrs}
        try:
            if hasattr(self, self.pivot):
                ref = getattr(self, self.pivot)
            elif self.pivot in self.base_fields.keys():
                ref = self.cleaned_data[self.pivot]
            else:
                raise NotImplementedError
        except (NotImplementedError, AttributeError):
            raise TypeError("self.pivot not well-defined")
        except TypeError:
            raise TypeError("mangled pivot definition")
        except KeyError:
            raise ValueError(
                f"defined pivot {self.pivot} not an attribute of self or a "
                f"member of self.base_fields"
            )
        try:
            selector = select(self.table_class).where(
                getattr(self.table_class, self.pivot) == ref
            )
            row = session.scalars(selector).one()
            for k, v in data.items():
                setattr(row, k, v)
            self._row = row
        except NoResultFound:
            data[self.pivot] = ref
            valid = set(dir(self.table_class))
            if constructor_method is None:
                constructor = self.table_class
            else:
                constructor = getattr(self.table_class, constructor_method)
                valid.update(get_argnames(constructor))
            self._row = constructor(
                **(keyfilter(lambda attr: attr in valid, data))
            )
        return self._row

    @autosession
    def commit(
        self, session=None, force_remake=False, constructor_method=None
    ):
        session.add(self.get_row(session, force_remake, constructor_method))
        session.commit()

    _row: AppTable = None
    pivot: str = "id"
    table_class: type[AppTable]
    extra_attrs: tuple[str] = ()


class JunctionForm(SAForm):
    """
    abstract-ish class for forms that help manage SQLAlchemy many-to-many
    relationships (django's metaclass structure prevents us from making it an
    actual ABC)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._associations = {k: {} for k in self.association_rules.keys()}
        self.assocation_specs = {k: [] for k in self.association_rules.keys()}

    @autosession
    def get_associations(
        self,
        table: type[JuncTable],
        session: Optional[Session] = None,
        force_remake: bool = False
    ) -> dict[str, JuncTable]:
        if 'existing' in (ad := self._associations[table]).keys():
            juncs = set(ad.get('present', ())).union(ad.get('missing', ()))
            if (
                all(sa_attached_to(j, session) for j in juncs)
                and force_remake is False
            ):
                return self._associations[table]
        rules = self.association_rules[table]
        junc_reference, referent = rules["pivot"]
        # noinspection PyTypeChecker
        exist_selector = select(table).where(
            getattr(table, junc_reference) == getattr(self, referent)
        )
        adict = defaultdict(list)
        # noinspection PyTypeChecker
        adict['existing'] = session.scalars(exist_selector).all()
        specs = {i: s for i, s in enumerate(self.assocation_specs[table])}
        for junc_row in adict['existing']:
            matches = [
                (i, s) for i, s in specs.items()
                if s == getattr(junc_row, rules["junc_pivot"])
            ]
            # mark table entries not specified in this form for deletion
            if len(matches) == 0:
                adict['missing'].append(junc_row)
            elif len(matches) > 1:
                raise InvalidRequestError(
                    "Only one matching row is expected here; table "
                    "contents appear invalid"
                )
            # update fields of existing, specified table entries
            else:
                for attr, val in matches[0][1].items():
                    setattr(junc_row, attr, val)
                adict['present'].append(junc_row)
                specs.pop(matches[0][0])
        # leftover specs are new table entries
        if len(specs) > 0:
            # shouldn't need to define self_attr on existing junc table rows
            row = self.get_row(session)
            for s in specs.values():
                junc_row = table()
                # TODO, maybe: sloppy?
                for attr, val in s.items():
                    setattr(junc_row, attr, val)
                setattr(junc_row, rules["self_attr"], row)
        self._associations[table] = dict(adict)
        return self._associations[table]

    @autosession
    def commit(
        self, session=None, force_remake=False, constructor_method=None
    ):
        removed = []
        for table in self.association_rules.keys():
            associations = self.get_associations(table, session, force_remake)
            session.add_all(associations['existing'])
            removed += associations['missing']
        row = self.get_row(session, force_remake, constructor_method)
        session.add(row)
        for r in removed:
            session.delete(r)
        session.commit()

    @autosession
    def _populate_junc_fields(self, session: Optional[Session] = None):
        for table, rules in self.association_rules.items():
            existing = self.get_associations(table, session)
            if len(existing) != 0:
                rules["populator"](existing)

    @cached_property
    def associated_form_fields(self):
        return set(
            filter(
                None,
                (r.get("form_field") for r in self.association_rules.values()),
            )
        )

    _associations: dict[type[JuncTable, dict[str, list[JuncTable]]]]
    association_rules: Mapping[type[JuncTable], AssociationRule]
    assocation_specs: dict[type[JuncTable], list[dict]]
