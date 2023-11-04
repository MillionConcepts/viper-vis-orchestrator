"""conventional django forms module"""
import datetime as dt
from functools import cached_property, wraps
from types import MappingProxyType as MPt
from typing import Optional, Union

from django import forms
from django.core.exceptions import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError, NoResultFound

# noinspection PyUnresolvedReferences
from viper_orchestrator.config import REQUEST_FILE_ROOT
from viper_orchestrator.db.session import autosession
from viper_orchestrator.db.table_utils import get_one
from viper_orchestrator.exceptions import (
    AlreadyLosslessError,
    AlreadyDeletedError,
)
from viper_orchestrator.visintent.tracking.sa_forms import JunctionForm, SAForm
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
LDST_EVAL_FIELDS = ("critical", "evaluation", "evaluator", "evaluation_notes")


def _blank_eval_info():
    return {
        hyp: {f: None for f in LDST_EVAL_FIELDS} | {"relevant": False}
        for hyp in LDST_IDS
    }


def _ldst_eval_record(row: JuncImageRequestLDST):
    return {f: getattr(row, f) for f in LDST_EVAL_FIELDS} | {"relevant": True}


def _blank_ldst_hypotheses():
    return {hyp: {"relevant": False, "critical": False} for hyp in LDST_IDS}


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


class EvaluationForm(SAForm):
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
        hyp: str,
        req_id: Optional[Union[int, str]] = None,
        session=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        if hyp not in LDST_IDS:
            raise ValueError(f"{hyp} is not a known LDST hypothesis.")
        self.hyp, self.req_id = hyp, int(req_id)
        # lazy way to get these attributes into the junction table while
        # maintaining our in-code attribute name conventions
        self.image_request_id = self.req_id
        self.ldst_id = self.hyp
        req = get_one(ImageRequest, self.req_id, session=session)
        self.needs_new_association = self.hyp not in [
            h.id for h in req.ldst_hypotheses
        ]

    def clean(self):
        good, bad = (self.cleaned_data.get(b) for b in ('good', 'bad'))
        if good and bad:
            self.evaluation = "incoherent"
        elif not (good or bad):
            self.evaluation = "missing"
        elif good:
            self.evaluation = True
        else:
            self.evaluation = False
        if self.evaluation == "incoherent":
            self.add_error(
                None,
                "cannot both support and not support hypothesis"
            )
        elif self.evaluation == "missing":
            self.add_error(
                None,
                "please specify yes or no"
            )
        super().clean()

    extra_attrs = ('evaluation', 'image_request_id', "ldst_id")

    @autosession
    def commit(self, session=None, **kwargs):
        # if self.needs_new_association is True:
        #     req = get_one(ImageRequest, self.req_id, session=session)
        #     hyp = get_one(LDST, self.hyp, session=session)
        #     req.ldst_hypotheses.append(hyp)
        #     session.add(req)
        super().commit(session=session)

    @classmethod
    def from_wsgirequest(cls, request):
        """intended to be called only from a view function."""
        return cls(
            request.POST,
            req_id=request.GET.get("req_id"),
            hyp=request.GET.get("hyp"),
        )

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
                "placeholder": "Enter your name to evaluate.",
            }
        )
    )

    pk_spec = MPt({'image_request_id': 'req_id', 'ldst_id': 'hyp'})
    junc_image_request_ldst_id = None
    table_class = JuncImageRequestLDST
    evaluation: Union[bool, str]
    image_request = None


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
        widget=forms.CheckboxInput(attrs={"class": "good-check"}),
    )
    bad = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "bad-check"}),
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
    pk_spec = "rec_id"

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
        elif (self.cleaned_data["bad"] or self.cleaned_data["good"]) is False:
            raise ValidationError("must select good or bad")
        if self.cleaned_data["bad"] == self.cleaned_data["good"]:
            raise ValidationError("cannot be both bad and good")
        self.verified = self.cleaned_data["good"]
        if (
            self.verified is False
            and len(self.cleaned_data["image_tags"]) == 0
            and len(self.cleaned_data["verification_notes"]) == 0
        ):
            raise ValidationError("give tags or notes to mark bad")
        self._construct_image_tag_attrs()
        del self.cleaned_data["image_tags"]

    verified: bool


class RequestForm(JunctionForm):
    """form for submitting or editing an image request."""

    def __init__(
        self,
        *args,
        image_request: Optional[ImageRequest] = None,
        ldst_hypotheses: Optional[dict[str, dict[str, bool]]] = None,
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
        if ldst_hypotheses is not None:
            self.ldst_hypotheses = ldst_hypotheses
        else:
            self.ldst_hypotheses = _blank_ldst_hypotheses()
        self.verification_status = self._get_verification_status()
        if len(self.product_ids) > 0:
            # make fields not required for already-taken images non-mandatory
            # and prohibit editing request information
            for field_name, field in self.fields.items():
                if field_name not in self.required_intent_fields:
                    field.required, field.disabled = False, True

    def _get_verification_status(self):
        if self.image_request is None:
            return {}
        return {
            r._pid: r.verified for r in self.image_request.image_records
        }

    @property
    def acquired(self):
        return len(self.image_request.image_records) > 0

    @property
    def pending_vis(self):
        return (
            self.acquired
            and any(v is None for v in self.verification_status.values())
        )

    @property
    def verification_code(self):
        if len(self.verification_status) == 0:
            return "no images"
        if all(v is None for v in self.verification_status.values()):
            return "none"
        if self.pending_vis:
            return "partial"
        if all(v is True for v in self.verification_status.values()):
            return "full (passed)"
        if all(v is True for v in self.verification_status.values()):
            return "full (passed)"
        if all(v is False for v in self.verification_status.values()):
            return "full (failed)"
        return "full (mixed)"

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
    def from_request_id(cls, *args, req_id, ldst_hypotheses, session=None):
        return cls(
            *args,
            image_request=get_one(
                ImageRequest,
                req_id,
                session=session,
            ),
            ldst_hypotheses=ldst_hypotheses,
        )

    @classmethod
    def from_wsgirequest(cls, wsgirequest, submitted: bool):
        """intended to be called only from a view function."""
        # identify existing request by request primary key
        info = wsgirequest.POST if submitted is True else wsgirequest.GET
        if submitted is False:
            args, parsed = (), None
        else:
            args = (info,)
            parsed = _blank_ldst_hypotheses()
            for name, checked in wsgirequest.POST.items():
                if not (
                    name.endswith("relevant") or name.endswith("critical")
                ):
                    continue
                hyp, quality = name.split("-")
                parsed[hyp][quality] = True if checked == "on" else False
        # frontend passes req_id in a url variable. it should be 'None' for a
        # newly-submitted request, python None when constructing a blank
        # request form, and an int or string representation of an int
        # corresponding to an ImageRequest table pk for display of or edits to
        # an existing request.
        if (req_id := wsgirequest.GET.get("req_id")) not in (None, "None"):
            return cls.from_request_id(
                *args, req_id=req_id, ldst_hypotheses=parsed
            )
        # otherwise simply populate / create blank form
        return cls(*args, ldst_hypotheses=parsed)

    @cached_property
    def eval_info(self):
        """
        dictionary of evaluation information. intended primarily to
        be sent to frontend as JSON to facilitate dynamic form creation.
        """
        self._eval_info |= {
            row.ldst_id: _ldst_eval_record(row)
            for row in self._relations[JuncImageRequestLDST].get(
                "existing", []
            )
        }
        return self._eval_info

    @property
    def critical_hypotheses(self):
        return [k for k, v in self.eval_info.items() if v['critical'] is True]

    @property
    def is_critical(self):
        return len(self.critical_hypotheses) > 0

    @property
    def evaluation_possible(self):
        if not self.acquired:
            return False
        if self.pending_vis:
            return False
        return True

    @property
    def pending_evaluations(self):
        if not self.evaluation_possible:
            return {}
        return [
            hyp for hyp, status in self.eval_info.items()
            if (status['critical'] is True) and (status['evaluation'] is None)
        ]

    @property
    def pending_eval(self):
        return len(self.pending_evaluations) > 0

    @property
    def eval_code(self):
        if len(self.verification_status) == 0:
            return ""
        if not self.is_critical:
            return "no critical LDST"
        if self.pending_vis:
            return "pending VIS"
        if len(self.pending_evaluations) == 0:
            return "full"
        if len(self.pending_evaluations) == len(self.critical_hypotheses):
            return "none"
        return "partial"

    # TODO: cut this in a clean way
    def _populate_from_junc_image_request_ldst(self, junc_rows):
        pass

    # other fields are only needed for outgoing image requests, not for
    # specifying intent metadata for already-taken images
    required_intent_fields = [
        "title",
        "justification",
        "ldst_hypotheses",
        "status",
    ]
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
        widget=forms.Textarea(
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
        for hyp, qualities in self.ldst_hypotheses.items():
            if qualities["relevant"] is False:
                continue
            attrs = {
                "critical": qualities["critical"],
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
        camera_request = self.cleaned_data["camera_request"]
        ct, mode = camera_request.split("_", maxsplit=1)
        self.camera_type = ct.upper()
        if self.camera_type == "HAZCAM":
            if mode == "any":
                self.hazcams = ("Any",)
            else:
                # TODO: change this if we have multiple hazcams
                self.hazcams = [
                    vis_instrument_aliases[camera_request.replace("_", " ")]
                ]
        else:
            self.imaging_mode = mode.upper()

    def clean(self):
        super().clean()
        self._construct_ldst_specs()
        if len(self.junc_specs[JuncImageRequestLDST]) == 0:
            self.add_error(None, "mark one or more hypotheses")
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

    ui_only_fields = ("camera_request", "need_360", "supplementary_file")
    pk_spec = "req_id"
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


@autosession
class PLSubmission(SAForm):
    """form for submitting an entry to the PL"""

    def __init__(self, *args, pid=None, pl_id=None, session=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_from_db(pid, pl_id, session)
        if self.entry.pl_id is not None:  # i.e., if it's an existing entry
            self.fields["rationale"].initial = self.entry.rationale

    def _init_from_db(self, pid, pl_id, session):
        if pl_id not in (None, "None"):
            try:
                entry = get_one(ProtectedListEntry, pl_id, session=session)
            except NoResultFound:
                raise NoResultFound(
                    f"No ProtectedList entry with pk {pl_id} exists."
                )
        elif pid not in (None, "None"):
            entry = ProtectedListEntry.from_pid(pid)
        else:
            raise ValueError(
                "must have at least pl_id or pid to create form"
            )
        self.has_lossless = entry.has_lossless
        if entry.pl_id is None and self.has_lossless:
            raise AlreadyLosslessError("Image already downlinked as lossless.")
        self.superseded = entry.superseded
        self.pl_id = entry.pl_id
        if (self.pl_id is None) and (self.superseded is True):
            raise AlreadyDeletedError("Image has already been deleted.")
        self.matching_pids = entry.matching_pids
        # we only require one reference pid
        self.pid = entry.matching_pids[0]
        self.entry = entry

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
    pk_spec = "pl_id"
    extra_attrs = ("pid", "request_time")


def request_supplementary_path(id_, fn="none"):
    # TODO: naming convention is slightly sketchy
    return REQUEST_FILE_ROOT / f"request_{id_}/{fn}"
