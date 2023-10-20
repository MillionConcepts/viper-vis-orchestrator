"""conventional django forms module"""
import datetime as dt
import warnings
from collections import defaultdict
from functools import cached_property
from typing import Optional, Mapping, Union, Callable

from cytoolz import keyfilter
from django import forms
from django.core.exceptions import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError, NoResultFound
from sqlalchemy.orm import Session, DeclarativeBase

from func import get_argnames
# noinspection PyUnresolvedReferences
from viper_orchestrator.config import REQUEST_FILE_ROOT
from viper_orchestrator.db import OSession
from viper_orchestrator.db.table_utils import sa_attached_to
from viper_orchestrator.visintent.tracking.db_utils import autosession
from viper_orchestrator.visintent.tracking.tables import (
    ProtectedListEntry,
)
from viper_orchestrator.visintent.visintent.settings import REQUEST_FILE_URL
from vipersci.pds.pid import vis_instruments, vis_instrument_aliases
from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.image_requests import ImageRequest, Status
from vipersci.vis.db.image_tags import ImageTag
from vipersci.vis.db.junc_image_record_tags import JuncImageRecordTag
from vipersci.vis.db.junc_image_req_ldst import JuncImageRequestLDST
from vipersci.vis.db.ldst import LDST
from vipersci.vis.db.light_records import luminaire_names


AppTable = Union[ImageRequest, ImageRecord, ProtectedListEntry]
JuncTable = Union[JuncImageRecordTag, JuncImageRequestLDST]


def initialize_fields():
    with OSession() as init_session:
        hypotheses = init_session.scalars(select(LDST)).all()
        ldst_ids = [hypothesis.id for hypothesis in hypotheses]
        image_tags = init_session.scalars(select(ImageTag)).all()
        tags = [tag.name for tag in image_tags]
    return {"ldst_ids": ldst_ids, "tags": tags}


FIELDS = initialize_fields()
LDST_IDS = FIELDS["ldst_ids"]
TAG_NAMES = FIELDS["tags"]

AssociationRule = Mapping[
    str, Union[str, JuncTable, tuple[str], Callable[[], None]]
]


class BadURLError(ValueError):
    pass


class CarelessMultipleChoiceField(forms.MultipleChoiceField):
    """
    aggressively skip Django's default choice validation.
    intended when we want to modify a field's options dynamically and don't
    want unnecessary handholding interfering with our modifications.
    """

    def __init__(self, *, choices, **kwargs):
        super().__init__(choices=choices, **kwargs)
        self.default_validators = []

    def validate(self, value):
        pass


class AssignRecordForm(forms.Form):

    def __init__(self, *args, rec_id):
        super().__init__(*args)
        try:
            with OSession() as session:
                selector = select(ImageRecord).where(ImageRecord.id == rec_id)
                self.image_record = session.scalars(selector).one()
        except InvalidRequestError:
            raise ValidationError(f"no ImageRecord with id {rec_id} exists")

    request_id = forms.IntegerField(
        widget=forms.TextInput(
            attrs={"id": "request-id-entry", "value": ""}
        )
    )

    def clean(self):
        super().clean()
        try:
            req_id = int(self.cleaned_data['request_id'])
        except ValueError:
            raise ValidationError("request id must be an integer")
        with OSession() as session:
            try:
                sel = select(ImageRequest).where(ImageRequest.id == req_id)
                self.image_request = session.scalars(sel).one()
                if self.image_request == self.image_record.image_request:
                    self.former_request = None
            except InvalidRequestError:
                raise ValidationError(
                    f"No ImageRequest with id {req_id} exists"
                )
            # try:
            #     # TODO: in_, etc.
            #     sel = select(ImageRequest.where(self.image_recordImageRequest.image_records)

    # def update_db(self):
    #
    #     request.image_records.append(self.image_record)
    #     session.add(request)
    #     session.commit()

    former_image_request: ImageRequest
    image_request: ImageRequest


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
    # noinspection PyTypeChecker
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
            # update fields of existing and specified table entries
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
    def _populate(self, session: Optional[Session] = None):
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


class VerificationForm(JunctionForm):
    """form for VIS verification of individual images."""

    def __init__(
        self,
        *args,
        image_record: Optional[ImageRecord] = None,
        pid: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        if image_record is None and pid is None:
            raise TypeError(
                "Cannot construct this form without a product ID or an "
                "ImageRecord object"
            )
        elif image_record is None:
            try:
                with OSession() as session:
                    image_record = session.scalars(
                        select(ImageRecord).where(ImageRecord._pid == pid)
                    ).one()
            except InvalidRequestError:
                raise InvalidRequestError(
                    "Cannot find a unique image matching this product ID"
                )
        self.image_record = image_record
    verified = forms.BooleanField(required=True)
    image_tags = forms.MultipleChoiceField(
        widget=forms.SelectMultiple(
            attrs={"id": "image-tags", "value": "", "placeholder": ""}
        ),
        choices=[(name, name) for name in TAG_NAMES],
    )
    verification_notes = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "id": "verification-notes",
                "placeholder": "any additional notes on image quality",
            }
        )
    )

    @property
    def association_rules(self):
        return {
            JuncImageRecordTag: {
                "target": ImageTag,
                "populator": self._populate_from_junc_image_record_tag,
                "pivot": ("image_record_id", "id"),
                "junc_pivot": "image_tag",
                "self_attr": "image_record",
                "form_field": "image_tag",
            }
        }

    def _populate_from_junc_image_record_tag(self, junc_rows):
        tag_names = []
        for row in junc_rows:
            tag_names.append(row.name)
        self.fields["image_tags"].initial = tag_names

    def _construct_associations(self):
        """construct JuncImageRecordTag attrs from form content"""
        with OSession() as session:
            for tag in self.cleaned_data["image_tags"]:
                attrs = {
                    "name": session.scalars(
                        select(ImageTag).where(ImageTag.name == tag)
                    )
                }
            self.associated[JuncImageRecordTag].append(attrs)

    def clean(self):
        super().clean()
        self._construct_associations()


class RequestForm(JunctionForm):
    """form for submitting or editing an image request."""

    def __init__(
        self,
        *args,
        image_request: Optional[ImageRequest] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.image_request = image_request
        if self.image_request is not None:
            self.product_ids = {
                r._pid for r in self.image_request.image_records
            }
            for field_name, field in self.fields.items():
                if field_name == "compression":
                    field.initial = image_request.compression.name.capitalize()
                elif field_name == "camera_request":
                    field.initial = self._image_request_to_camera_request(
                        image_request
                    )
                elif field_name in dir(image_request):
                    field.initial = getattr(image_request, field_name)
            self.id = image_request.id
            with OSession() as session:
                self._populate(session)

        else:
            self.product_ids = set()
        if len(self.product_ids) > 0:
            # make fields not required for already-taken images non-mandatory
            # and prohibit editing request information
            for field_name, field in self.fields.items():
                if field_name not in self.required_intent_fields:
                    field.required, field.disabled = False, True
            self.fields['critical'].disabled = False
            self.fields['luminaires'].initial = None

    def filepaths(self):
        # TODO, maybe: is this pathing a little sketchy?
        try:
            filepath = next(
                request_supplementary_path(self.id).parent.iterdir(),
            )
        except (StopIteration, FileNotFoundError, AttributeError):
            return None, None
        file_url = REQUEST_FILE_URL / f"request_{self.id}/{filepath.name}"
        return filepath.name, file_url

    @classmethod
    def from_request_id(cls, *args, rid):
        with OSession() as session:
            # noinspection PyTypeChecker
            selector = select(ImageRequest).where(ImageRequest.id == rid)
            return cls(*args, image_request=session.scalars(selector).one())

    @classmethod
    def from_wsgirequest(cls, wsgirequest, submitted: bool):
        """intended to be called only from a view function."""
        # identify existing request by request primary key
        info = wsgirequest.POST if submitted is True else wsgirequest.GET
        args = () if submitted is False else (info,)
        if (rid := info.get('request_id')) is not None:
            return cls.from_request_id(*args, rid=rid)
        # otherwise simply populate / create blank form
        return cls(*args)

    # other fields are only needed for outgoing image requests, not for
    # specifying intent metadata for already-taken images
    required_intent_fields = ["title", "justification", "ldst_hypotheses"]
    title = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={"placeholder": "short title", "id": "image-title"}
        ),
    )
    justification = forms.CharField(
        required=True,
        widget=forms.Textarea(
            attrs={
                "placeholder": "full description",
                "id": "image-justification",
            }
        ),
    )
    ldst_hypotheses = forms.MultipleChoiceField(
        required=True,
        widget=forms.SelectMultiple(
            attrs={
                "id": "ldst-elements",
                "value": "",
                "placeholder": "",
                "style": "height: 10rem",
            }
        ),
        initial=[],
        choices=[(id_, id_) for id_ in LDST_IDS],
    )
    critical = CarelessMultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(
            attrs={"id": "ldst-critical", "value": "", "placeholder": ""}
        ),
        choices=[],
    )

    status = forms.ChoiceField(
        required=True,
        widget=forms.Select(attrs={"id": "status", "value": "WORKING"}),
        choices=[(e.name, e.name) for e in list(Status)],
        initial="WORKING",
    )

    users = forms.CharField(
        required=True,
        widget=forms.TextInput(
            {"placeholder": "requesting users", "id": "requesting-users"}
        ),
    )
    target_location = forms.CharField(
        required=True,
        widget=forms.Textarea(
            {
                "placeholder": "target description/location",
                "id": "target-location",
            }
        ),
    )
    rover_location = forms.CharField(
        required=True,
        widget=forms.Textarea(
            {"placeholder": "rover location", "id": "rover-location"}
        ),
    )
    camera_request = forms.ChoiceField(
        required=True,
        widget=forms.Select(
            attrs={"value": "navcam_left", "id": "camera-request"}
        ),
        choices=[
            ("navcam_left", "NavCam Left"),
            ("navcam_right", "NavCam Right"),
            ("navcam_stereo", "NavCam Stereo"),
            ("navcam_panorama", "NavCam Panorama"),
            ("aftcam_left", "AftCam Left"),
            ("aftcam_right", "AftCam Right"),
            ("aftcam_stereo", "AftCam Stereo"),
            ("hazcam_any", "HazCam (any)"),
            ("hazcam_forward_port", "HazCam Forward Port"),
            ("hazcam_forward_starboard", "HazCam Forward Starboard"),
            ("hazcam_aft_port", "HazCam Aft Port"),
            ("hazcam_aft_starboard", "HazCam Aft Starboard"),
        ],
    )
    rover_orientation = forms.CharField(
        widget=forms.TextInput(
            {
                "placeholder": "rover orientation (if relevant)",
                "id": "rover-orientation",
            }
        ),
        required=False,
    )
    compression = forms.ChoiceField(
        required=True,
        widget=forms.Select(attrs={"id": "compression-request"}),
        initial="LOSSY",
        choices=[("LOSSY", "Lossy"), ("LOSSLESS", "Lossless")],
    )
    # TODO: the following fields will be hidden by js for non-pano images
    luminaires = forms.MultipleChoiceField(
        widget=forms.SelectMultiple(attrs={"id": "luminaires-request"}),
        # TODO: not working
        initial=["default"],
        required=False,
        choices=[
            ("default", "default"),
            ("none", "none"),
            *((k, v) for k, v in luminaire_names.items()),
        ],
    )
    # Note that django checkboxinput widgets must have required=False to allow
    # unchecked values to pass default validation
    caltarget_required = forms.BooleanField(
        widget=forms.CheckboxInput(
            attrs={"id": "caltarget-required", "class": "pano-only"}
        ),
        required=False,
        initial=True,
    )
    aftcam_pair = forms.BooleanField(
        widget=forms.CheckboxInput(
            attrs={"id": "aftcam-pair", "class": "pano-only"}
        ),
        required=False,
    )
    chin_down_navcam_pair = forms.BooleanField(
        widget=forms.CheckboxInput(
            attrs={"id": "chin-down-navcam-pair", "class": "pano-only"},
        ),
        required=False,
    )
    need_360 = forms.BooleanField(
        widget=forms.CheckboxInput(
            attrs={"id": "need-360", "class": "pano-only"}
        ),
        initial=True,
        required=False,
    )
    # TODO: restrict range
    # these will be hidden in js when need_360 is selected
    first_slice_index = forms.IntegerField(
        widget=forms.NumberInput(
            attrs={"id": "first-slice", "class": "pano-only slice-field"}
        ),
        required=False,
    )
    last_slice_index = forms.IntegerField(
        widget=forms.NumberInput(
            attrs={"id": "last-slice", "class": "pano-only slice-field"}
        ),
        required=False,
    )
    # may contain either a duration in milliseconds or the strings
    # "default", "overexposed", "neutral", or "underexposed" -- don't really
    # need to validate it, I don't think?
    exposure_time = forms.CharField(
        widget=forms.TextInput(
            attrs={"id": "exposure-time", "value": "default"}
        ),
        initial="default",
    )
    supplementary_file = forms.FileField(required=False)

    # properties to help webpage formatting. they denote fields to hide or
    # reveal depending on whether a panorama is requested, and, if so, whether
    # full-360 is selected. they are used on the frontend to add CSS classes
    # to HTML elements that are then used as references by js.

    def _css_class_fields(self, css_class):
        return [
            field_name
            for field_name, field in self.fields.items()
            if css_class in field.widget.attrs.get("class", "")
        ]

    @cached_property
    def pano_only_fields(self):
        return self._css_class_fields("pano-only")

    @cached_property
    def slice_fields(self):
        return self._css_class_fields("slice-field")

    @cached_property
    def association_rules(self):
        return {
            JuncImageRequestLDST: {
                "target": LDST,
                "pivot": ("image_request_id", "id"),
                "junc_pivot": "ldst",
                "self_attr": "image_request",
                "form_field": "ldst_hypotheses",
                "populator": self._populate_from_junc_image_request_ldst,
            }
        }

    def _populate_from_junc_image_request_ldst(self, junc_rows):
        ldst_hypotheses, critical = [], []
        for row in junc_rows:
            ldst_hypotheses.append(row.ldst_id)
            if row.critical is True:
                critical.append(row.ldst_id)
        self.fields["ldst_hypotheses"].initial = ldst_hypotheses
        self.fields["critical"].choices = [(h, h) for h in ldst_hypotheses]
        self.fields["critical"].initial = critical

    def _construct_associations(self):
        """construct JuncImageRequestLDST attrs from form content"""
        if 'ldst_hypotheses' not in self.cleaned_data:
            return
        with OSession() as session:
            for hyp in self.cleaned_data["ldst_hypotheses"]:
                attrs = {
                    "critical": hyp in self.cleaned_data["critical"],
                    "ldst": session.scalars(
                        select(LDST).where(LDST.id == hyp)
                    ).one(),
                }
                self.associated[JuncImageRequestLDST].append(attrs)

    @staticmethod
    def _image_request_to_camera_request(request: ImageRequest):
        """
        reformat fields of an ImageRequest into the single camera request
        field used in this form
        """
        if request.camera_type.name == "HAZCAM":
            # TODO: change this if we _do_ have multiple hazcams in a request
            if not isinstance(request.hazcams, str):
                cam = request.hazcams[0]
            else:
                cam = request.hazcams
            if cam == "Any":
                camera_request = "hazcam_any"
            else:
                camera_request = vis_instruments[cam].lower().replace(" ", "_")
        else:
            camera_request = "_".join(
                s.lower()
                for s in (request.camera_type.name, request.imaging_mode.name)
            )
        return camera_request

    def _reformat_camera_request(self):
        """
        reformat camera request as expressed in the user interface into
        imaging mode/camera type/hazcam seq as desired by the ImageRequest
        table. assumes this is a bound form that has been populated from the
        UI.
        """
        # note that only aftcams/navcams have imaging_mode
        if self.fields['camera_request'].disabled is True:
            return
        request = self.cleaned_data["camera_request"]
        ct, mode = request.split("_", maxsplit=1)
        self.camera_type = ct.upper()
        self.generalities = ("Any",)
        if self.camera_type == "HAZCAM":
            if mode == "any":
                self.hazcams = ("Any",)
            else:
                # TODO: change this if we have multiple hazcams
                self.hazcams = [
                    vis_instrument_aliases[request.replace("_", " ")]
                ]
        else:
            self.hazcams = ("Any",)
            self.imaging_mode = mode.upper()

    def clean(self):
        super().clean()
        self._construct_associations()
        self._reformat_camera_request()
        if len(self.cleaned_data.get("luminaires", [])) > 2:
            raise ValidationError("A max of two luminaires may be requested")
        if not self.cleaned_data.get("luminaires"):
            self.cleaned_data["luminaires"] = ["default"]
        for k, v in self.cleaned_data.items():
            if (
                isinstance(v, (list, tuple))
                and k not in self.association_rules
            ):
                # TODO: ensure comma separation is good enough
                self.cleaned_data[k] = ",".join(v)
        self.request_time = dt.datetime.now().astimezone(dt.timezone.utc)
        for fieldname in self.ui_only_fields:
            del self.cleaned_data[fieldname]
        return self.cleaned_data

    ui_only_fields = (
        "camera_request",
        "need_360",
        "supplementary_file",
        "ldst_hypotheses",
        "critical",
    )

    # this is actually an optional set of integers, but, in form submission,
    # we retain / parse it as a string for UI reasons. TODO, maybe: clean
    #  that up
    product_ids: Optional[set[str]] = None
    id: Optional[int] = None
    request_time: Optional[dt.datetime] = None
    table_class = ImageRequest
    imaging_mode = None
    camera_type = None
    hazcams = None
    generalities = None


class AlreadyLosslessError(ValidationError):
    pass


class AlreadyDeletedError(ValidationError):
    pass


class PLSubmission(forms.Form):
    """form for submitting an entry to the PL"""

    def __init__(self, *args, product_id=None, pl_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        entry, self.superseded = None, None
        if pl_id not in (None, "None"):
            with OSession() as session:
                entry = session.scalars(
                    select(ProtectedListEntry).where(
                        ProtectedListEntry.pl_id == int(pl_id)
                    )
                ).one()
        elif product_id not in (None, "None"):
            entry = ProtectedListEntry.from_pid(product_id)
        else:
            raise ValueError(
                "must have at least pl_id or product_id to create form"
            )
        self.has_lossless = entry.has_lossless
        if entry.pl_id is None and self.has_lossless:
            raise AlreadyLosslessError("Image already downlinked as lossless.")
        self.superseded = entry.superseded
        self.pl_id = entry.pl_id  # TODO: sloppy
        if (self.pl_id is None) and (self.superseded is True):
            raise AlreadyDeletedError("Image has already been deleted.")
        self.matching_pids = entry.matching_pids
        if entry.pl_id is not None:  # i.e., if it's an existing entry
            self.fields["rationale"].initial = entry.rationale
        self.product_id = entry.matching_pids[0]

    rationale = forms.CharField(
        required=True,
        widget=forms.Textarea(
            attrs={
                "id": "pl-rationale",
                "placeholder": "rationale for placement on protected list",
            }
        ),
    )

    def clean(self):
        super().clean()
        self.request_time = dt.datetime.now()
        return self.cleaned_data

    table_class = ProtectedListEntry
    request_time = None


def request_supplementary_path(id_, fn="none"):
    # TODO: naming convention is slightly sketchy
    return REQUEST_FILE_ROOT / f"request_{id_}/{fn}"
