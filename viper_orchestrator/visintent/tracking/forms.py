"""conventional django forms module"""
import datetime as dt
import warnings
from typing import Optional

from cytoolz import keyfilter
from django import forms
from django.core.exceptions import ValidationError
from sqlalchemy import select

from viper_orchestrator.db import OSession
from viper_orchestrator.db.table_utils import (
    image_request_capturesets,
    get_capture_ids,
    capture_ids_to_product_ids,
)
from viper_orchestrator.visintent.tracking.tables import (
    ProtectedListEntry,
)
from viper_orchestrator.visintent.visintent.settings import (
    MEDIA_ROOT,
    MEDIA_URL,
)
from vipersci.pds.pid import vis_instruments, vis_instrument_aliases
from vipersci.vis.db.image_requests import ImageRequest
from vipersci.vis.db.junc_image_req_ldst import JuncImageRequestLDST
from vipersci.vis.db.ldst import LDST
from vipersci.vis.db.light_records import luminaire_names


with OSession() as init_session:
    hypotheses = init_session.scalars(select(LDST)).all()
    LDST_IDS = [hypothesis.id for hypothesis in hypotheses]


class BadURLError(ValueError):
    pass


# TODO: may be a more clever way to handle this on the frontend
class CarelessMultipleChoiceField(forms.MultipleChoiceField):
    """
    skip choice validation. for fields whose options we may modify dynamically.
    """

    def validate(self, value):
        pass

    default_validators = []


class RequestForm(forms.Form):
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
        self.pano_only_fields = [
            field_name
            for field_name, field in self.fields.items()
            if "pano-only" in field.widget.attrs.get("class", "")
        ]
        self.slice_fields = [
            field_name
            for field_name, field in self.fields.items()
            if "slice-field" in field.widget.attrs.get("class", "")
        ]

    def filepaths(self):
        # TODO, maybe: is this pathing a little sketchy?
        try:
            filepath = next(
                request_supplementary_path(self.id).parent.iterdir(),
            )
        except (StopIteration, FileNotFoundError, AttributeError):
            return None, None
        # noinspection PyUnboundLocalVariable
        file_url = (
            f"{MEDIA_URL}request_supplementary_data/"
            f"request_{self.id}/{filepath.name}"
        )
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
                "style": 'height: 10rem'
            }
        ),
        choices=[(id_, id_) for id_ in LDST_IDS]
    )
    critical = CarelessMultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(
            attrs={'id': 'ldst-critical', 'value': '', 'placeholder': ''}
        ),
        choices=[]
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

    @property
    def associated_tables(self):
        return {
            'junc_image_request_ldst': {
                'junc': JuncImageRequestLDST,
                'pivot': ('image_request_id', 'id'),
                'self_attr': 'image_request',
            }
        }

    def _construct_associations(self):
        """construct JuncImageRequestLDST attrs from form content"""
        associations = []
        with OSession() as session:
            for hyp in self.cleaned_data['ldst_hypotheses']:
                attrs = {
                    'critical': hyp in self.cleaned_data['critical'],
                    'ldst': session.scalars(
                        select(LDST).where(LDST.id == hyp)
                    ).one()
                }
                associations.append(attrs)
        self.cleaned_data['junc_image_request_ldst'] = associations

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
        request = self.cleaned_data['camera_request']
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
                    and k not in self.associated_tables
            ):
                # TODO: ensure comma separation is good enough
                self.cleaned_data[k] = ",".join(v)
        self.request_time = dt.datetime.now().astimezone(dt.timezone.utc)
        for fieldname in self.ui_only_fields:
            del self.cleaned_data[fieldname]
        return self.cleaned_data

    ui_only_fields = (
        'camera_request',
        'need_360',
        'supplementary_file',
        'ldst_hypotheses',
        'critical'
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
    return MEDIA_ROOT / f"request_supplementary_data/request_{id_}/{fn}"
