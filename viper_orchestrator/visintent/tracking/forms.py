"""conventional django forms module"""
import datetime as dt
from functools import cached_property, wraps, partial
from typing import Optional, Union

from django import forms
from django.core.exceptions import ValidationError
from dustgoggles.structures import listify
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError, NoResultFound
from sqlalchemy.orm import Session

# noinspection PyUnresolvedReferences
from viper_orchestrator.config import REQUEST_FILE_ROOT
from viper_orchestrator.db import OSession
from viper_orchestrator.db.session import autosession
from viper_orchestrator.db.table_utils import get_one
from viper_orchestrator.exceptions import (
    AlreadyLosslessError,
    AlreadyDeletedError,
)
from viper_orchestrator.visintent.tracking.sa_forms import JunctionForm
from viper_orchestrator.visintent.tracking.tables import ProtectedListEntry
from viper_orchestrator.visintent.visintent.settings import REQUEST_FILE_URL
from vipersci.pds.pid import vis_instruments, vis_instrument_aliases
from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.image_requests import ImageRequest, Status
from vipersci.vis.db.image_tags import ImageTag
from vipersci.vis.db.junc_image_record_tags import JuncImageRecordTag
from vipersci.vis.db.junc_image_req_ldst import JuncImageRequestLDST
from vipersci.vis.db.ldst import LDST
from vipersci.vis.db.light_records import luminaire_names


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


@autosession
def initialize_options(session=None):
    hypotheses = session.scalars(select(LDST)).all()
    ldst_ids = [hypothesis.id for hypothesis in hypotheses]
    image_tags = session.scalars(select(ImageTag)).all()
    tags = [tag.name for tag in image_tags]
    return {"ldst_ids": ldst_ids, "tags": tags}


# on import, construct sets of form options representing
#  sets of legal associated objects for many-to-many relations
OPTIONS = initialize_options()
LDST_IDS = OPTIONS["ldst_ids"]
TAG_NAMES = OPTIONS["tags"]
LDST_EVAL_FIELDS = ('critical', 'evaluation', 'evaluator', 'evaluation_notes')


def _blank_eval_info():
    return {hyp: {f: None for f in LDST_EVAL_FIELDS} for hyp in LDST_IDS}


def _ldst_eval_record(row: JuncImageRequestLDST):
    return {f: getattr(row, f) for f in LDST_EVAL_FIELDS}


def _db_init_trywrap(func):
    """
    sugar for handling exceptions in attempts to init forms from db records
    """

    @wraps(func)
    def trywrapped(self, entry, *identifiers, **kwargs):
        try:
            func(self, entry, *identifiers, **kwargs)
        except (NoResultFound, InvalidRequestError):
            raise NoResultFound(
                f"No {entry.__class__.__name__} with id(s): "
                f"{tuple(filter(None, identifiers))} exists"
            )
        except ValueError as ve:
            if "int" in str(ve):
                raise TypeError("specified identifier must be an integer")
            raise ve

    return trywrapped


class AssignRecordForm(forms.Form):
    """very simple form for associating an ImageRecord with an ImageRequest."""

    @autosession
    def __init__(self, *args, rec_id=None, req_id=None, session=None):
        super().__init__(*args)
        if self.is_bound:
            self.rec_id = int(args[0]["rec_id"])
            return
        self._init_from_db(rec_id, req_id, session)
        self.fields["req_id"].initial = self.req_id

    @_db_init_trywrap
    def _init_from_db(self, rec_id, req_id, session):
        self.rec_id = int(rec_id)
        if req_id not in (None, ""):
            self.req_id = int(req_id)
        else:
            self.req_id = None
        # wasteful to do this lookup twice, but best for strictness --
        # never want to put an unbound version of this form on a page
        get_one(ImageRecord, self.rec_id, session=session)

    req_id = forms.IntegerField(
        label="request id",
        widget=forms.TextInput(attrs={"id": "request-id-entry", "value": ""}),
    )

    @autosession
    def clean(self, session=None):
        super().clean()
        if "req_id" in self.errors:
            # lazy way to override default phrase i don't like
            self.errors["req_id"] = ["request id must be an integer."]
            return
        self.req_id = self.cleaned_data["req_id"]
        try:
            get_one(ImageRequest, self.req_id, session=session)
        except (InvalidRequestError, NoResultFound):
            self.add_error(
                "req_id", f"no ImageRequest with id {self.req_id} exists"
            )

    @autosession
    def commit(self, session=None):
        image_request = get_one(ImageRequest, self.req_id, session=session)
        image_record = get_one(ImageRecord, self.rec_id, session=session)
        former_request = image_record.image_request
        if former_request == image_request:
            return  # nothing to do!
        image_request.image_records.append(image_record)
        session.add(image_request)
        if former_request is not None:
            former_request.image_records = [
                r for r in former_request.image_records if r != image_record
            ]
            session.add(former_request)
        session.commit()


def ldst_junc_rules(self):
    """
    shared junc rule constructor for forms that access JuncImageRequestLDST
    """
    return {
        "target": LDST,
        "pivot": ("image_request_id", "req_id"),
        "junc_pivot": "ldst_id",
        "junc_instance_spec_key": "ldst",
        "self_attr": "image_request",
        "form_field": "ldst_hypotheses",
        "populator": getattr(self, "_populate_from_junc_image_request_ldst"),
    }


class EvaluationForm(JunctionForm):
    """
    form for science evaluation of image requests. this is _only_ used on the
    backend to help manage relations. we dynamically construct HTML forms
    whose values will be used to construct these objects on the frontend,
    populating those forms from the DOM representation of a RequestForm.
    """

    @autosession
    def __init__(
        self,
        *args,
        ldst_id: str,
        image_request: Optional[ImageRequest] = None,
        req_id: Optional[Union[int, str]] = None,
        session: Optional[Session] = None,
        **kwargs,
    ):
        if ldst_id not in LDST_IDS:
            raise ValueError(f"{ldst_id} is not a known LDST hypothesis.")
        super().__init__(*args, **kwargs)
        self._initialize_from_db(image_request, req_id, session=session)
        self._populate_junc_fields()

    @_db_init_trywrap
    def _initialize_from_db(
        self,
        image_request: Optional[ImageRequest],
        req_id: Optional[Union[str, int]],
        session: Optional[Session],
    ):
        if image_request is None and req_id is None:
            raise TypeError(
                "Cannot construct this form without an ImageRequest id "
                "(pk) or an ImageRequest object"
            )
        elif image_request is not None:
            self.image_request = image_request
        else:
            self.image_request = get_one(
                ImageRequest, int(req_id), session=session
            )
        self.req_id = self.image_request.id

    good = forms.BooleanField(required=False)
    bad = forms.BooleanField(required=False)
    evaluation_notes = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "evaluation-notes-text",
                "placeholder": "Enter any notes.",
            }
        ),
        required=False,
    )
    evaluator = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "evaluator-text",
                "placeholder": "Enter your name to verify.",
            }
        )
    )

    @property
    def junc_rules(self):
        return {
            "target": LDST,
            "pivot": ("image_request_id", "req_id"),
            "junc_pivot": "ldst_id",
            "junc_instance_spec_key": "ldst",
            "update_only": True,
        }


class VerificationForm(JunctionForm):
    """form for VIS verification of individual images."""

    @autosession
    def __init__(
        self,
        *args,
        image_record: Optional[ImageRecord] = None,
        rec_id: Optional[Union[int, str]] = None,
        pid: Optional[str] = None,
        session=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._initialize_from_db(image_record, pid, rec_id, session=session)
        self.rec_id = self.image_record.id
        self.verified = self.image_record.verified
        if self.verified is not None:
            self.fields["bad"].initial = not self.verified
            self.fields["good"].initial = self.verified
        self.fields[
            "verification_notes"
        ].initial = self.image_record.verification_notes
        self._populate_junc_fields()

    @_db_init_trywrap
    def _initialize_from_db(self, image_record, pid, rec_id, *, session):
        if image_record is None and pid is None and rec_id is None:
            raise TypeError(
                "Cannot construct this form without a product ID, an "
                "ImageRecord pk, or an ImageRecord object"
            )
        elif image_record is not None:
            self.image_record = image_record
        elif rec_id is not None:
            self.image_record = get_one(
                ImageRecord, int(rec_id), session=session
            )
        elif pid is not None:
            self.image_record = get_one(
                ImageRecord, pid, pivot="_pid", session=session
            )

    good = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'good-check'})
    )
    bad = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'bad-check'})
    )
    image_tags = forms.MultipleChoiceField(
        widget=forms.SelectMultiple(
            attrs={"id": "image-tags", "value": "", "placeholder": ""}
        ),
        required=False,
        choices=[(name, name) for name in TAG_NAMES],
    )
    verification_notes = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "id": "verification-notes",
                "placeholder": "any additional notes on image quality",
            }
        ),
        required=False,
    )
    table_class = ImageRecord
    pk_field = "rec_id"

    @property
    def junc_rules(self):
        return {
            JuncImageRecordTag: {
                "target": ImageTag,
                "populator": self._populate_from_junc_image_record_tag,
                "pivot": ("image_record_id", "rec_id"),
                "junc_pivot": "image_tag_id",
                "junc_instance_spec_key": "image_tag",
                "self_attr": "image_record",
                "form_field": "image_tags",
            }
        }

    extra_attrs = ("verified",)

    def _populate_from_junc_image_record_tag(self, junc_rows):
        tag_names = []
        for row in junc_rows:
            tag_names.append(row.image_tag.name)
        self.fields["image_tags"].initial = tag_names

    @autosession
    def _construct_image_tag_attrs(self, session=None):
        """construct JuncImageRecordTag attrs from form content"""
        for tag in self.cleaned_data["image_tags"]:
            attrs = {
                "image_tag": session.scalars(
                    select(ImageTag).where(ImageTag.name == tag)
                ).one()
            }
            self.junc_specs[JuncImageRecordTag].append(attrs)

    def clean(self):
        super().clean()
        if "bad" not in self.cleaned_data and "good" not in self.cleaned_data:
            raise ValidationError("must select good or bad")
        if self.cleaned_data["bad"] == self.cleaned_data["good"]:
            raise ValidationError("cannot be both bad and good")
        self.verified = self.cleaned_data["good"]
        if (
            self.verified is False
            and len(self.cleaned_data["image_tags"]) == 0
            and len(self.cleaned_data["verification_notes"]) == 0
        ):
            self.errors[
                "needs justification: "
            ] = "To mark an image as bad, you must provide tags or notes."
        self._construct_image_tag_attrs()
        del self.cleaned_data["image_tags"]

    verified: bool


class RequestForm(JunctionForm):
    """form for submitting or editing an image request."""

    def __init__(
        self,
        *args,
        image_request: Optional[ImageRequest] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._eval_info = _blank_eval_info()
        self.image_request = image_request
        if self.image_request is not None:
            self.product_ids = {
                r._pid for r in self.image_request.image_records
            }
            for field_name, field in self.fields.items():
                if field_name == "compression":
                    field.initial = image_request.compression.name
                elif field_name == "status":
                    field.initial = image_request.status.name
                elif field_name == "camera_request":
                    field.initial = self._image_request_to_camera_request(
                        image_request
                    )
                elif field_name == "luminaires":
                    field.initial = image_request.luminaires.split(",")
                elif field_name in dir(image_request):
                    field.initial = getattr(image_request, field_name)
            self.req_id = image_request.id
            self._populate_junc_fields()
        else:
            self.product_ids = set()
        if len(self.product_ids) > 0:
            # make fields not required for already-taken images non-mandatory
            # and prohibit editing request information
            for field_name, field in self.fields.items():
                if field_name not in self.required_intent_fields:
                    field.required, field.disabled = False, True
            self.fields["critical"].disabled = False

    def filepaths(self):
        # TODO, maybe: is this pathing a little sketchy?
        try:
            filepath = next(
                request_supplementary_path(self.req_id).parent.iterdir(),
            )
        except (StopIteration, FileNotFoundError, AttributeError):
            return None, None
        file_url = REQUEST_FILE_URL / f"request_{self.req_id}/{filepath.name}"
        return filepath.name, file_url

    @classmethod
    @autosession
    def from_request_id(cls, *args, req_id, session=None):
        return cls(
            *args, image_request=get_one(ImageRequest, req_id, session=session)
        )

    @classmethod
    def from_wsgirequest(cls, wsgirequest, submitted: bool):
        """intended to be called only from a view function."""
        # identify existing request by request primary key
        info = wsgirequest.POST if submitted is True else wsgirequest.GET
        args = () if submitted is False else (info,)
        if (req_id := info.get("req_id")) is not None:
            return cls.from_request_id(*args, req_id=req_id)
        # otherwise simply populate / create blank form
        return cls(*args)

    @property
    def eval_info(self):
        """
        dictionary of evaluation information. intended primarily to
        be sent to frontend as JSON to facilitate dynamic form creation.
        """
        self._eval_info |= {
            row.ldst_id: _ldst_eval_record(row)
            for row
            in self._relations[JuncImageRequestLDST].get('existing', [])
        }
        return self._eval_info

    def _populate_from_junc_image_request_ldst(self, junc_rows):
        ldst_hypotheses, critical = [], []
        for row in junc_rows:
            ldst_hypotheses.append(row.ldst_id)
            if row.critical is True:
                critical.append(row.ldst_id)
        self.fields["ldst_hypotheses"].initial = ldst_hypotheses
        self.fields["critical"].choices = [(h, h) for h in ldst_hypotheses]
        self.fields["critical"].initial = critical

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
    def junc_rules(self):
        return {JuncImageRequestLDST: ldst_junc_rules(self)}

    extra_attrs = (
        "imaging_mode",
        "camera_type",
        "hazcams",
        "request_time",
    )

    @autosession
    def _construct_ldst_specs(self, session=None):
        """construct JuncImageRequestLDST attrs from form content"""
        if "ldst_hypotheses" not in self.cleaned_data:
            return
        for hyp in self.cleaned_data["ldst_hypotheses"]:
            attrs = {
                "critical": hyp in self.cleaned_data["critical"],
                "ldst": get_one(LDST, hyp, session=session),
            }
            self.junc_specs[JuncImageRequestLDST].append(attrs)

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
        if self.camera_type != "HAZCAM":
            self.hazcams = ("Any",)
        if self.fields["camera_request"].disabled is True:
            return
        request = self.cleaned_data["camera_request"]
        ct, mode = request.split("_", maxsplit=1)
        self.camera_type = ct.upper()
        if self.camera_type == "HAZCAM":
            if mode == "any":
                self.hazcams = ("Any",)
            else:
                # TODO: change this if we have multiple hazcams
                self.hazcams = [
                    vis_instrument_aliases[request.replace("_", " ")]
                ]
        else:
            self.imaging_mode = mode.upper()

    def clean(self):
        super().clean()
        self._construct_ldst_specs()
        self._reformat_camera_request()
        if len(self.cleaned_data.get("luminaires", [])) > 2:
            raise ValidationError("A max of two luminaires may be requested")
        if not self.cleaned_data.get("luminaires"):
            self.cleaned_data["luminaires"] = ["default"]
        for k, v in self.cleaned_data.items():
            if isinstance(v, (list, tuple)) and k not in self.junc_rules:
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
    pk_field = "req_id"
    # this is actually an optional set of integers, but, in form submission,
    # we retain / parse it as a string for UI reasons. TODO, maybe: clean
    #  that up
    product_ids: Optional[set[str]] = None
    req_id: Optional[int] = None
    request_time: Optional[dt.datetime] = None
    table_class = ImageRequest
    imaging_mode = None
    camera_type = None
    hazcams = None


class PLSubmission(JunctionForm):
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
