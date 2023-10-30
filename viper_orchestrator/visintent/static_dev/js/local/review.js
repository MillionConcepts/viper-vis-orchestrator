// noinspection JSUnusedGlobalSymbols

// shared data objects sent from backend
/**
 * verification status by ImageRecord ID
 * @type {Object<string, Object<string, verificationRecord>>}
 */
const verifications = JSON.parse(gid('verifications').innerText)
/**
 * summary verification status codes for each ImageRequest
 * @type {Object<string, reqInfoRecord>}
 */
const reqInfo = JSON.parse(gid('req_info').innerText)

// shared DOM objects
const criticalFilterButton = gid('filter-critical-button')
const verifiedFilterButton = gid('filter-verified-button')
const evalFilterButton = gid('eval-filter-button')
const evalFilterStatus = gid('eval-filter-status')

/**
 * sort object entries by iso-formatted datetime
 * @param {string} a
 * @param {string} b
 * @param {boolean} descending
 * @returns {number}
 */
const gentimeCompareFn = function(a, b, descending=true) {
    const s = descending ? [a[1], b[1]] : [b[1], a[1]]
    if (s[0]['gentime'] > s[1]['gentime']) {
        return -1
    } else if (s[0]['gentime'] < s[1]['gentime']) {
        return 1
    }
    return 0
}

// styles for verification status
const vStyle = {
    "null": {"text": "unverified", "color": "#D79A00"},
    "true": {"text": "passed", "color": "#00CC11"},
    "false": {"text": "failed", color: "#BB2222"}
}

// selectively filter display of verification rows
const maybeHideVRows = function(_event = null) {
    // TODO: inefficient although easy
    const vRows = document.getElementsByClassName('verification-row')
    for (let row of vRows) {
        if (row.classList.contains('non-critical-row') && filteringCritical) {
            row.style.display = "none"
        }
        else if (row.classList.contains('verified-row') && filteringVerified) {
            row.style.display = "none"
        }
        else {
            row.style.display = ""
        }
    }
}
// selectively filter display of evaluation rows
const maybeHideERows = function(_event = null) {
    // TODO: inefficient and messy
    const eRows = document.getElementsByClassName('evaluation-row')
    for (let row of eRows) {
        if (evalFilterSetting === 0) {
            if (row.classList.contains('not-pending-evaluation-row')) {
                row.style.display = "none"
            }
            else {
                row.style.display = ""
            }
        }
        else if (evalFilterSetting === 1) {
            if (row.classList.contains('unfulfilled-row')) {
                row.style.display = "none"
            }
            else {
                row.style.display = ""
            }
        }
        else if (evalFilterSetting === 2) {
            row.style.display = ""
        }
    }
}

// toggle functions for verification display filters
const toggleCritical = function (setting=null) {
    setting = setting === null ? !filteringCritical : setting
    filteringCritical = setting
    if (filteringCritical === false) {
        criticalFilterButton.innerText = "turn on"
    }
    else {
        criticalFilterButton.innerText = "turn off"
    }
    maybeHideVRows()
}
const toggleVerified = function (setting=null) {
    setting = setting === null ? !filteringVerified : setting
    filteringVerified = setting
    if (filteringVerified === false) {
        verifiedFilterButton.innerText = "turn on"
    }
    else {
        verifiedFilterButton.innerText = "turn off"
    }
    maybeHideVRows()
}

// three-mode evaluation display filter
const switchEvalFilter = function (setting=null) {
    setting = setting === null ? (evalFilterSetting + 1) % 3 : setting
    evalFilterSetting = setting
    if (setting === 0) {
        evalFilterStatus.innerText = "showing pending"
        evalFilterButton.innerText = "show all fulfilled"
    }
    if (setting === 1) {
        evalFilterStatus.innerText = "showing fulfilled"
        evalFilterButton.innerText = "show all critical"
    }
    if (setting === 2) {
        evalFilterStatus.innerText = "showing all critical"
        evalFilterButton.innerText = "show pending"
    }
    maybeHideERows()
}

const initDisplayFilters = function(_event) {
    toggleVerified(filteringVerified)
    toggleCritical(filteringCritical)
    switchEvalFilter(evalFilterSetting)
}

// constructor functions for review status tables
const buildVerificationTable = function(_event) {
    const vTable = gid('table-body-verification')
    let rowNum = 0
    const bodyFragment = new DocumentFragment
    objsort(verifications, gentimeCompareFn).forEach(
        function([_id, {verified, critical, gentime, req_id, pid}]) {
            const pCell = W(pid, "a")
            pCell.href = pid
            const vCell = W(vStyle[String(verified)]['text'], "p")
            vCell.style.color = vStyle[String(verified)]['color']
            const critMark = critical ? 'X' : ''
            let rCell
            if (req_id !== null) {
                rCell = W(String(req_id), "a")
                rCell.href = `imagerequest?req_id=${req_id}`
            }
            else {
                rCell = ""
            }
            const cells = [
                pCell, vCell, critMark, rCell, gentime
            ].map(e => W(e, "td"))
            const tr = W(cells, "tr", 'verification-row')
            tr.id = `verification-row-${rowNum}`
            if (critical !== true) {
                tr.classList.add('non-critical-row')
            }
            if (verified !== null) {
                tr.classList.add('verified-row')
            }
            rowNum++
            bodyFragment.append(tr)
        })
    vTable.appendChild(bodyFragment)
}

/**
 * @param {Record<string, evaluationRecord>} evalRecs
 * @returns {Object<string, ?boolean>}
 */
const extractCriticalStatus = function(evalRecs) {
    const critHyps = {}
    Object.entries(evalRecs).filter(e => e[1].critical).forEach(
        ([hyp, {evaluation}]) => critHyps[hyp] = evaluation
    )
    return critHyps
}

const buildEvaluationTable = function(_event) {
    const eTable = gid('table-body-evaluation')
    const bodyFragment = new DocumentFragment
    let rowNum = 0
    Object.entries(reqInfo).forEach(
        function([reqID, info]) {
            if (info['critical'] !== true) {
                return
            }
            const iCell = W(reqID, "a")
            iCell.href = `/imagerequest?req_id=${reqID}`
            const tCell = W(info['title'], "a")
            tCell.href = `/imagerequest?req_id=${reqID}`
            const vCell = W(info['vcode'], "p")
            vCell.style.color = reqVColor[info['vcode']]
            const eCell = W(info['ecode'], "p")
            eCell.style.color = reqEColor[info['ecode']]
            const cells = [
                iCell, tCell, info['status'], vCell, eCell
            ].map(e => W(e, "td"))
            const tr = W(cells, "tr", "evaluation-row")
            tr.id = `evaluation-row-${rowNum}`
            if (info['ecode'] === '') {
                tr.classList.add("unfulfilled-row")
            }
            if (!info['pending_eval']) {
                tr.classList.add("not-pending-evaluation-row")
            }
            bodyFragment.append(tr)
        })
    eTable.appendChild(bodyFragment)
}

const unHideContent = function() {
    gid("content").style.display = "block"
}

document.addEventListener("DOMContentLoaded", buildVerificationTable)
document.addEventListener("DOMContentLoaded", buildEvaluationTable)
document.addEventListener("DOMContentLoaded", maybeHideVRows)
document.addEventListener("DOMContentLoaded", initDisplayFilters)
document.addEventListener("DOMContentLoaded", revealDefault)
document.addEventListener("DOMContentLoaded", unHideContent)