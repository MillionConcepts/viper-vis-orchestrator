// shared data objects sent from backend
/**
 * summary review status codes for each ImageRequest
 * @type {Object<string, reqInfoRecord>}
 */
const reqInfo = JSON.parse(gid('req_info').innerText)
/**
 * complete evaluation status for each ImageRequest
 * @type {Object<string, Object<string, evaluationRecord>>}
 */
const evalByReq = JSON.parse(gid('eval_by_req').innerText)
/**
 * complete evaluation status for each LDST hyp
 * @type {Object<string, Object<string, evaluationRecord>>}
 */
const evalByHyp = JSON.parse(gid('eval_by_hyp').innerText)
/**
 * summary evaluation status for each LDST hyp
 * @type {Object<string, ldstEvalSummary>}
 */
const ldstSummary = JSON.parse(gid('ldst_summary_info').innerText)

const buildSummaryTable = function(_event) {
    const sTable = gid('table-body-summary')
    let rowNum = 0
    const bodyFragment = new DocumentFragment
    Object.entries(ldstSummary).forEach(
        function(
            [hyp, {relevant, critical, acquired, pending_vis, pending_eval, passed, failed}]
        ) {
            const cells = [
                hyp, relevant, critical, acquired, pending_vis, pending_eval, passed, failed
            ].map(e => W(String(e), "td"))
            const tr = W(cells, "tr", 'summary-row')
            tr.id = `summary-row-${rowNum}`
            rowNum++
            bodyFragment.append(tr)
        })
    sTable.appendChild(bodyFragment)
}

const requestRowStatus = function() {
    this.pending = []
    this.passed = []
    this.failed = []
}

const buildHypTable = function(_event) {
    const hTable = gid('table-body-hyp')
    const bodyFragment = new DocumentFragment
    let rowNum = 0
    Object.entries(evalByHyp).forEach(
        function([hyp, requests]) {
            const spacerRow = W(
                ["", "", "", ""].map(e => W(e, "td")), "tr", "ldst-spacer-row"
            )
            bodyFragment.append(spacerRow)
            const titleRow = W(
                [hyp, "", "", ""].map(e => W(e, "td")), "tr", "ldst-header-row"
            )
            bodyFragment.append(titleRow)
            Object.entries(requests).forEach(
                function (
                    [reqID, {critical, evaluation}]
                ) {
                    if (critical !== true) {
                        return
                    }
                    const info = reqInfo[reqID]
                    const spacer = W("", "p")
                    const iCell = W(reqID, "a")
                    iCell.href = `/imagerequest?req_id=${reqID}`
                    const tCell = W(info.title, "a")
                    tCell.href = `/imagerequest?req_id=${reqID}`
                    let status, statusColor
                    if (info.acquired !== true) {
                        [status, statusColor] = ["no images", "lightskyblue"]
                    } else if (info.pending_vis === true) {
                        [status, statusColor] = ["pending VIS", "palegoldenrod"]
                    } else if (evaluation === null) {
                        [status, statusColor] = ["pending evaluation", "#D79A00"]
                    } else if (evaluation === true) {
                        [status, statusColor] = ["passed", "#00CC11"]
                    } else if (evaluation === false) {
                        [status, statusColor] = ["failed", "#BB2222"]
                    } else {
                        throw new Error("unable to parse request relationship")
                    }
                    const sCell = W(status, "p")
                    sCell.style.color = statusColor
                    const cells = [spacer, iCell, tCell, sCell].map(e => W(e, "td"))
                    const tr = W(cells, "tr", "hyp-request-row")
                    tr.id = `hyp-row-${hyp}-${rowNum}`
                    bodyFragment.append(tr)
                })
            })
    hTable.appendChild(bodyFragment)
}

const buildRequestTable = function(_event) {
    const rTable = gid('table-body-requests')
    const bodyFragment = new DocumentFragment
    let rowNum = 0
    Object.entries(reqInfo).forEach(
        function([reqID, info]) {
            const iCell = W(reqID, "a")
            iCell.href = `/imagerequest?req_id=${reqID}`
            const tCell = W(info['title'], "a")
            tCell.href = `/imagerequest?req_id=${reqID}`
            const status = new requestRowStatus
            if (info['evaluation_possible'] === true) {
                Object.entries(evalByReq[reqID]).forEach(
                    function ([hyp, {critical, evaluation}]) {
                        if (critical !== true) {
                            return
                        }
                        if (info['pending_evaluations'].includes(hyp)) {
                            status.pending.push(hyp)
                        }
                        else if (evaluation === true) {
                            status.passed.push(hyp)
                        }
                        else if (evaluation === false) {
                            status.failed.push(hyp)
                        }
                    }
                )
            }
            const vCell = W(info['vcode'], "p")
            vCell.style.color = reqVColor[info['vcode']]
            const eCell = W(info['ecode'], "p")
            eCell.style.color = reqEColor[info['ecode']]
            const hCells = ['pending', 'passed', 'failed'].map(
                t => W(status[t].join(', '), 'p')
            )
            hCells[0].style.color = "#D79A00"
            hCells[1].style.color = "#00CC11"
            hCells[2].style.color = "#BB2222"
            const cells = [
                iCell, tCell, info['status'], vCell, eCell, ...hCells
            ].map(e => W(e, "td"))
            const tr = W(cells, "tr", "requests-row")
            tr.id = `requests-row-${rowNum}`
            if (info['ecode'] === '') {
                tr.classList.add("unfulfilled-row")
            }
            if (!info['pending_eval']) {
                tr.classList.add("not-pending-evaluation-row")
            }
            bodyFragment.append(tr)
        })
    rTable.appendChild(bodyFragment)
}

const unHideContent = function() {
    gid("content").style.display = "block"
}
const linkHash = new URL(document.baseURI).hash
let defaultTable
if (linkHash.includes('hyp')) {
    defaultTable = 'hyp'
}
else if (linkHash.includes('requests')) {
    defaultTable = 'requests'
}
else {
    defaultTable = 'summary'
}
