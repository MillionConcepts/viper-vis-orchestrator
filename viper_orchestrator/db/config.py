from pathlib import Path

from vipersci.vis.db.image_records import ImageRecord
from vipersci.vis.db.image_requests import ImageRequest
from vipersci.vis.db.image_stats import ImageStats
from vipersci.vis.db.image_tags import ImageTag, taglist
from vipersci.vis.db.junc_image_record_tags import JuncImageRecordTag
from vipersci.vis.db.junc_image_req_ldst import JuncImageRequestLDST
from vipersci.vis.db.ldst import LDST
from vipersci.vis.db.ldst_verification import LDSTVerification
from vipersci.vis.db.light_records import LightRecord
from viper_orchestrator.visintent.tracking.tables import AppBase

BASES = [
    AppBase,
    ImageRecord,
    ImageRequest,
    ImageStats,
    ImageTag,
    JuncImageRecordTag,
    JuncImageRequestLDST,
    LDST,
    LDSTVerification,
    LightRecord
]

TEST_DB_PATH = (Path(__file__).parent / 'postgres').absolute()
TEST = True

# where are we writing our scratch products? for dev, should match MEDIA_ROOT
# in visintent.visintent.settings
# TODO: replace this with the real output path
DATA_ROOT = Path(__file__).parent.parent / "media/products/data/"
BROWSE_ROOT = Path(__file__).parent.parent / "media/products/browse/"
