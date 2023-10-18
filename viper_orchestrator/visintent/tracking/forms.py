"""conventional django forms module"""
import datetime as dt
import warnings
from functools import cached_property
from typing import Optional, Mapping, Union, Callable

from cytoolz import keyfilter
from django import forms
from django.core.exceptions import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session, DeclarativeBase

# noinspection PyUnresolvedReferences
from viper_orchestrator.config import REQUEST_FILE_ROOT
from viper_orchestrator.db import OSession
from viper_orchestrator.db.table_utils import (
    image_request_capturesets,
    get_capture_ids,
    capture_ids_to_product_ids,
)
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


class JunctionForm(forms.Form):
    """
    "abstract" class for forms that help manage SQLAlchemy many-to-many
    relationships (django's metaclass structure prevents us from making it an
    actual ABC)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.associated = {k: [] for k in self.association_rules.keys()}

    # noinspection PyTypeChecker
    def get_associations(
        self, table: type[DeclarativeBase], session: Session
    ) -> list[DeclarativeBase]:
        junc_reference, referent = self.association_rules[table]["pivot"]
        exist_selector = select(table).where(
            getattr(table, junc_reference) == getattr(self, referent)
        )
        return session.scalars(exist_selector).all()

    def _populate(self, session: Session):
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

    association_rules: Mapping[type[DeclarativeBase], AssociationRule]
    associated: dict[type[DeclarativeBase], list[dict]]


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
    verified = forms.BooleanField(required=True)

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
        capture_id=None,
        image_request: Optional[ImageRequest] = None,
        request_id=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.capture_id, self.image_request = capture_id, image_request
        if self.capture_id is not None and len(self.capture_id) > 0:
            self.product_ids = capture_ids_to_product_ids(self.capture_id)
            # want to keep this a string for compatibility with the UI
            if isinstance(self.capture_id, set):
                self.capture_id = ",".join(str(ci) for ci in self.capture_id)
            self.capture_id = self.capture_id.replace(" ", "").strip(",")
            # make fields not required for already-taken images non-mandatory
            # and prohibit editing request information
            for field_name, field in self.fields.items():
                if field_name not in self.required_intent_fields:
                    field.required, field.disabled = False, True
        if image_request is not None:
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
            if request_id is not None:
                warnings.warn(
                    "request_id and image_request simultaneously passed to "
                    "RequestForm constructor; undesired behavior may result"
                )
        elif request_id is not None:
            self.id = int(request_id)
        with OSession() as session:
            self._populate(session)

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
    def from_request_id(cls, id):
        with OSession() as session:
            # noinspection PyTypeChecker
            selector = select(ImageRequest).where(ImageRequest.id == id)
            request = session.scalars(selector).one()
            return cls(
                capture_id=get_capture_ids(request), image_request=request
            )

    @classmethod
    def from_capture_id(cls, capture_id):
        request_id = None
        cset = set(map(int, str(capture_id).split(",")))
        for rid, cids in image_request_capturesets().items():
            if cids == cset:
                return cls.from_request_id(request_id)
            elif not cset.isdisjoint(cids):
                raise ValueError(
                    "proposed image request overlaps partially with "
                    "assigned capture ids of an existing image request"
                )
        return cls(capture_id=capture_id)

    @classmethod
    def from_wsgirequest(cls, wsgirequest):
        """intended to be called only from a view function."""

        # identify request by either associated capture id (if it exists!) or
        # by request primary key
        info = keyfilter(
            lambda k: k in ("capture_id", "request_id"), wsgirequest.GET
        )
        if ("capture_id" in info) and ("request_id" in info):
            raise BadURLError(
                "cannot accept both capture and request id in this URL"
            )
        if (rid := info.get("request_id")) is not None:
            return cls.from_request_id(rid)
        elif (cid := info.get("capture_id")) is not None:
            return cls.from_capture_id(cid)
        return cls()

    # other fields are only needed for outgoing image requests, not for
    # specifying intent metadata for already-taken images
    required_intent_fields = ["title", "justification", "ldst"]
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
    capture_id: Optional[str] = None
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
