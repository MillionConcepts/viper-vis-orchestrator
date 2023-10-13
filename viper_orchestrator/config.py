"""orchestrator configuration."""
from pathlib import Path

from viper_orchestrator.visintent.tracking.tables import ProtectedListEntry
from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.image_requests import ImageRequest
from vipersci.vis.db.image_stats import ImageStats
from vipersci.vis.db.image_tags import ImageTag
from vipersci.vis.db.junc_image_record_tags import JuncImageRecordTag
from vipersci.vis.db.junc_image_req_ldst import JuncImageRequestLDST
from vipersci.vis.db.ldst import LDST
from vipersci.vis.db.ldst_verification import LDSTVerification
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
    JuncImageRecordTag,
    JuncImageRequestLDST,
    LDST,
    LDSTVerification,
    LightRecord,
    ProtectedListEntry,
]

# path structure for application

# postgres database folder
TEST_DB_PATH = (Path(__file__).parent / 'vis_db').absolute()
PROD_DB_PATH = Path("/mnt/db/vis_db")
DB_PATH = TEST_DB_PATH if TEST is True else PROD_DB_PATH

# media directories (web app can only serve files under MEDIA_ROOT)
TEST_MEDIA_ROOT = Path(__file__).parent.parent / "media"
PROD_MEDIA_ROOT = Path("/mnt/media/")
MEDIA_ROOT = TEST_MEDIA_ROOT if TEST is True else PROD_MEDIA_ROOT
PRODUCT_ROOT = MEDIA_ROOT / "products"
DATA_ROOT = PRODUCT_ROOT / "data"
BROWSE_ROOT = PRODUCT_ROOT / "browse"

# application and supplementary data logs
TEST_LOG_ROOT = Path(__file__).parent.parent / "logs"
PROD_LOG_ROOT = Path("/mnt/logs/")
LOG_ROOT = TEST_LOG_ROOT if TEST is True else PROD_LOG_ROOT
STATION_LOG_ROOT = LOG_ROOT / "station"
LIGHTSTATE_LOG_FILE = LOG_ROOT / "lightstate.csv"

# static files (fonts, css, etc.) for web application
STATIC_ROOT = MEDIA_ROOT / "assets"

# location of mock data files for testing
MOCK_DATA_ROOT = Path(__file__).parent / "mock_data/mock_events_build_9"
MOCK_EVENT_PARQUET = MOCK_DATA_ROOT / "events.parquet"
MOCK_BLOBS_FOLDER = MOCK_DATA_ROOT / "blobs"

ROOTS = DATA_ROOT, BROWSE_ROOT, LOG_ROOT, STATION_LOG_ROOT
for root in ROOTS:
    root.mkdir(parents=True, exist_ok=True)
