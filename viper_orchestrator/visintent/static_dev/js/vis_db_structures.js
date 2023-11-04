/** type definitions for objects sent from backend as JSON. these correspond
 * to type aliases and preprocessing functions in vis_db_structures.py.
 */

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
 * @property {boolean} acquired - have any images been acquired yet?
 * @property {string} edit_url - link to request edit page
 * @property {string} request_time - ISO-formatted modification time
 * @property {number[]} rec_ids - pks of all associated ImageRecords
 * @property {string[]} rec_pids - VIS IDs of all associated ImageRecords
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

/**
 * @typedef imageRecBrief
 * @type {object}
 * @property {number} product_id - VIS ID
 * @property {string} instrument_name - human-readable camera name
 * @property {string} thumbnail_url - link to on-disk thumbnail
 * @property {string} browse_url - link to on-disk JPEG browse image
 * @property {string} label_url - link to on-disk JSON label
 */

// TODO: should not be in this file, and should just be CSS
const reqVColor = {
    "full (mixed)": "lightskyblue",
    "full (passed)": "#00CC11",
    "full (failed)": "#BB2222",
    "partial": "#D79A00",
    "none": "#D79A00",
    "no images": "#666677"
}
const reqEColor = {
    "unfulfilled": "#666677",  // no images
    "full": "#00CC11",
    "partial": "#D79A00",
    "none": "#D79A00",
    "pending VIS": "palegoldenrod"
}