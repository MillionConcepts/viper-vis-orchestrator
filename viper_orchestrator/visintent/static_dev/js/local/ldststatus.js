/**
 * evaluation status, organized such that top level is ImageRequest id
 * and second level is LDST id
 * @type {Object<string, Object<string, evaluationRecord>>}
 */
const evalByReq = JSON.parse(gid('eval_by_req').innerText)
/**
 * evaluation status, organized such that top level is LDST id
 * and second level is ImageRequest id
 * @type {Object<string, Object<string, evaluationRecord>>}
 */
const evalByHyp = JSON.parse(gid('eval_by_hyp').innerText)
