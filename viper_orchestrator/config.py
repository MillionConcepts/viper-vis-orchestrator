"""orchestrator configuration."""
from __future__ import annotations
from pathlib import Path
import sys

from viper_orchestrator.visintent.tracking.tables import ProtectedListEntry
from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.image_requests import ImageRequest
from vipersci.vis.db.image_stats import ImageStats
from vipersci.vis.db.image_tags import ImageTag
from vipersci.vis.db.pano_records import PanoRecord
from vipersci.vis.db.junc_image_pano import JuncImagePano
from vipersci.vis.db.junc_image_record_tags import JuncImageRecordTag
from vipersci.vis.db.junc_image_req_ldst import JuncImageRequestLDST
from vipersci.vis.db.ldst import LDST
from vipersci.vis.db.light_records import LightRecord

# are we running in test mode? primarily affects file write behavior
TEST = True

# yamcs parameters we know we care about at the moment
PARAMETERS = (
    "/ViperGround/Images/ImageData/Hazcam_back_left_icer",
    "/ViperGround/Images/ImageData/Hazcam_back_right_icer",
    "/ViperGround/Images/ImageData/Hazcam_front_left_icer",
    "/ViperGround/Images/ImageData/Hazcam_front_right_icer",
    "/ViperGround/Images/ImageData/Navcam_left_icer",
    "/ViperGround/Images/ImageData/Navcam_right_icer",
    "/ViperGround/Images/ImageData/Aftcam_left_icer",
    "/ViperGround/Images/ImageData/Aftcam_right_icer",
    "/ViperRover/LightsControl/state",
)

# tables the orchestrator interacts with
BASES = [
    ImageRecord,
    ImageRequest,
    ImageStats,
    ImageTag,
    JuncImagePano,
    JuncImageRecordTag,
    JuncImageRequestLDST,
    LDST,
    LightRecord,
    PanoRecord,
    ProtectedListEntry,
]


def set_up_paths(test: bool = TEST):
    module = sys.modules[__name__]
    paths = {
        # postgres database root directory
        'TEST_DB_ROOT': (Path(__file__).parent / 'vis_db').absolute(),
        'PROD_DB_ROOT': Path("/mnt/db/vis_db"),
        # media directories (web app can only serve files under MEDIA_ROOT)
        'TEST_MEDIA_ROOT': Path(__file__).parent.parent / "media",
        'PROD_MEDIA_ROOT': Path("/mnt/media/"),
        # application and supplementary data logs
        'TEST_LOG_ROOT': Path(__file__).parent.parent / "logs",
        'PROD_LOG_ROOT': Path("/mnt/logs/")
    }
    which = {True: 'TEST', False: 'PROD'}[test]
    for pre in ['DB', 'MEDIA', 'LOG']:
        paths[f'{pre}_ROOT'] = paths[f'{which}_{pre}_ROOT']

    # data and browse products (images, labels, etc.)
    paths['PRODUCT_ROOT'] = paths['MEDIA_ROOT'] / "products"
    paths['DATA_ROOT'] = paths['PRODUCT_ROOT'] / "data"
    paths['BROWSE_ROOT'] = paths['PRODUCT_ROOT'] / "browse"
    # user-uploaded files
    paths['REQUEST_FILE_ROOT'] = paths['MEDIA_ROOT'] / "request_files"
    # static files (fonts, css, js, etc.) for web application
    paths['STATIC_ROOT'] = paths['MEDIA_ROOT'] / "assets"
    paths['STATION_LOG_ROOT'] = paths['LOG_ROOT'] / "station"
    paths['LIGHTSTATE_LOG_FILE'] = paths['LOG_ROOT'] / "lightstate.csv"
    # location of mock data files for testing
    paths['MOCK_DATA_ROOT'] = (
        Path(__file__).parent / "mock_data/mock_events_build_9"
    )
    paths['MOCK_EVENT_PARQUET'] = paths['MOCK_DATA_ROOT'] / "events.parquet"
    paths['MOCK_BLOBS_FOLDER'] = paths['MOCK_DATA_ROOT'] / "blobs"
    roots = (
        paths['DATA_ROOT'],
        paths['BROWSE_ROOT'],
        paths['STATION_LOG_ROOT'],
        paths['REQUEST_FILE_ROOT'],
        paths['STATIC_ROOT'],
    )
    for root in roots:
        root.mkdir(parents=True, exist_ok=True)
    for k, v in paths.items():
        setattr(module, k, v)
    return paths


set_up_paths()
