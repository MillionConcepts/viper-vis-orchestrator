// type definitions for objects sent from backend as JSON
/**
 * @typedef evaluationRecord
 * @property {?boolean} relevant - relevant to this hypothesis
 * @property {?boolean} critical - critical to this hypothesis
 * @property {?boolean} evaluation - supports? null means not yet evaluated.
 * @property {?string} evaluator - who evaluated it?
 * @property {?string} evaluation_notes - notes on decision?
 */

/**
 * @typedef verificationRecord
 * @property {?boolean} verified - good/bad? null means not yet reviewed.
 * @property {?boolean} critical - LDST critical? null === no associated request.
 * @property {string} gentime - yamcs generation time in truncated iso format
 * @property {?number} req_id - associated request, if any
 * @property {string} pid - VIS product ID
 */

/**
 * @typedef reqInfoRecord
 * @property {string} ecode - evaluation status code
 * @property {string} vcode - verification status code
 * @property {string} status - request status (working, planned, etc.)
 * @property {string} title - request title
 * @property {boolean} critical - any critical LDST?
 * @property {boolean} pending_eval - any critical LDST pending science evaluation?
 *  this property is always false if no images have been acquired and/or any are
 *  pending VIS verification.
 * @property {boolean} pending_vis - any images pending VIS verification?
 * @property {boolean} acquired - have any images been accquired yet?
 */

/**
 * @typedef ldstEvalSummary
 * @property {number} relevant - requests marked relevant to this hypothesis
 * @property {number} critical - requests marked critical to this hypothesis
 * @property {number} pending_eval - critical requests that _can_ be evaluated
 *      but have not been
 * @property {number} pending_vis - critical requests whose associated images
 *      have not all been VIS verified
 * @property {number} passed - critical requests that passed evaluation
 * @property {number} failed - critical requests that failed evaluation
 */

/**
 * @typedef protectedListRecord
 * @property {number} ccu - which CCU is/was the image stored on
 * @property {number} image_id - CCU storage slot
 * @property {string} request_time - creation or edit time of request
 * @property {string} rationale - listed rationale for request
 * @property {string} pl_url - URL for request editing
 * @property {boolean} has_lossless - is there an associated lossless product?
 *      (implies request was fulfilled)
 * @property {boolean} superseded - did the image get deleted on the rover?
 * @property {string} pid - PID used to create PL request
 */

const reqVColor = {
    "full (mixed)": "lightskyblue",
    "full (passed)": "#00CC11",
    "full (failed)": "#BB2222",
    "partial": "#D79A00",
    "none": "#D79A00",
    "no images": "palegoldenrod"
}
const reqEColor = {
    "": "black",  // no images
    "full": "#00CC11",
    "partial": "#D79A00",
    "none": "#D79A00",
    "pending VIS": "palegoldenrod"
}