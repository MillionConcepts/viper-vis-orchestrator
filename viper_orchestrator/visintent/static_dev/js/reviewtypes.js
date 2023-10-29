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
 * @property {boolean} pending_vis - any images pending VIS verification?
 *   this property is always false if the request is not ready to be evaluated.
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