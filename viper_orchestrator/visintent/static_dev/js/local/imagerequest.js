// noinspection JSUnusedGlobalSymbols

/* shared DOM object references */
const pidHeader = gid('pid-header-div')
const verificationStatusP = gid('verification-status-p')
const reviewStatusDiv = gid('review-status-div')
const toggleButton = gid('evaluation-toggle')
const criticalChecks = document.getElementsByClassName('critical-check')
const cameraRequest = document.getElementById('camera-request');
const needs360 = document.getElementById('need-360');
const panoOnlyInputs = document.getElementsByClassName('pano-only');
const sliceInputs = document.getElementsByClassName('slice-field');
/**
 * @type {HTMLTableElement}
 */
const evalTable = gid('eval-table');
/**
 * @type {HTMLTableSectionElement}
 */
const evalTableBody = gid('eval-table-body');
const evalForms = document.getElementsByClassName('eval-form')

// passthrough data
/**
 * @type {Object<str, ?boolean>}
 */
const verifications = maybeParse("verification_json")
/**
 * @type {reqInfoRecord}
 */
const reqInfo = maybeParse("req_info_json")
/**
 * @type {Object}
 * @property {!string} hyp
 * @property {!string} errors
 * @property {!boolean} success
 */
const evalUIStatus = maybeParse("eval_ui_status")
let evalUIErrors
if (evalUIStatus.errors !== undefined) {
    evalUIErrors = JSON.parse(evalUIStatus.errors)
}
else {
    evalUIErrors = {}
}
const requestErrors = maybeParse("request_error_json")
/**
 * @typedef evalState
 * @property {string} id
 * @property {string|boolean} value
 */
/**
 * @type Object
 * @property {string[]} critical
 * @property {evalState[]} evals
 */
const liveFormState = maybeParse("live_form_state")
/**
 *
 * @typedef evaluationRecord
 * @type {object}
 * @property {!boolean} evaluation
 * @property {!string} evaluator
 * @property {!boolean} critical
 * @property {!string} evaluation_notes
 * @property {boolean} relevant
 */

/**
 *
 * @type {Object<string, evaluationRecord>}
 */
const evaluations = maybeParse("eval_json")
const reviewPossible = Object.keys(verifications).length > 0

const toggleEvalTable = function() {
    const isVisible = evalTable.style.display !== "none"
    evalTable.style.display = isVisible ? "none" : "table"
    toggleButton.innerText = isVisible ? "show evaluation interface" : "hide evaluation interface"
}
/**
 * @param {string} identifier
 * @param {string} name
 * @param {?string} text
 * @param {?string} placeholder
 * @returns {HTMLElement}
 */
const textAreaFactory = function(identifier, name, text=null, placeholder=null) {
    const textArea = document.createElement("textarea")
    textArea.innerText = text === null ? "" : text
    textArea.placeholder = placeholder === null ? "" : placeholder
    textArea.classList.add(`${name}-text`)
    textArea.classList.add('eval-input-element')
    textArea.name = name
    textArea.id = `${identifier}-${name}`
    return textArea
}
/**
 * @param {string} identifier
 * @param {string} name
 * @param {boolean} checked
 * @param {?string|HTMLElement} paired
 * @param {boolean} nameID
 * @param {boolean} strict
 * @returns {HTMLElement}
 */
const checkFactory = function(
    identifier, name, checked=false, paired=null, nameID=false, strict=false
) {
    const checkbox = document.createElement("input")
    checkbox.type = "checkbox"
    checkbox.checked = checked
    checkbox.id = `${identifier}-${name}-check`
    checkbox.name = nameID ? `${identifier}-${name}` : name
    checkbox.classList.add(`${name}-check`)
    let target = null
    if (typeof(paired) === "string") {
        target = `${identifier}-${paired}-check`
    }
    else {
        target = paired
    }
    if (paired !== null) {
        if (strict === false) {
            checkbox.onclick = () => unCheck(target)
        }
        else {
            checkbox.onclick = () => disableCheck(target, checkbox)
        }
    }
    checkbox.classList.add("eval-input-element")
    return checkbox
}

/**
 * @param {string} hyp
 * @returns HTMLElement[]
*/
const evalRowFactory = function(hyp) {
    const eval = evaluations[hyp]
    const status = eval['evaluation']
    const hypCell = W(hyp, "p", "hyp-eval-cell")
    const goodCheck = checkFactory(hyp, "good", status===true, "bad")
    const badCheck = checkFactory(hyp, "bad", status===false, "good")
    const goodBad = W(
        [
            W(L(goodCheck, "YES"), "div"),
            W(L(badCheck, "NO"), "div")
        ],
        "div",
        "good-bad-field"
    )
    const notes = textAreaFactory(
        hyp, "evaluation_notes",  eval['evaluation_notes'], 'Enter any notes.'
    )
    const evaluator = textAreaFactory(
        hyp, 'evaluator', eval['evaluator'], 'Enter your name.'
    )
    const button = W("evaluate", "button")
    button.id = `${hyp}-submit-button`
    button.type = "submit"
    const cells = [
        hypCell, goodBad, L(notes), L(evaluator), L(button)
    ].map(e => W(e, "td"))
    addForm(`${hyp}-eval-form`, ...cells)
    return cells
}
const populateHypotheses = function(_event) {
    const hypFragment = new DocumentFragment
    // NOTE: weird key because of weird Django Form convention
    // TODO: can make less weird on backend
    const {__all__: hypErrors} = requestErrors
    if (hypErrors !== undefined) {
        const errDiv = hypFragment.appendChild(W("", "div", "hyp-errors"))
        errDiv.appendChild(W("errors:", "h4"))
        hypErrors.forEach(
            e => errDiv.appendChild(W(e.message, "p"))
        )
    }
    Object.entries(evaluations).forEach(function([hyp, {relevant, critical}]){
        const ldstCheck = checkFactory(
            hyp, 'relevant', relevant===true, "critical", true, true
        )
        const critCheck = checkFactory(
            hyp, 'critical', critical===true, null, true
        )
        critCheck.disabled = !relevant
        const row = W([...L(ldstCheck, hyp), ...L(critCheck, "critical?")], "div")
        hypFragment.appendChild(row)
    })
    gid("ldst-field-div").appendChild(hypFragment)

}

function insertErrorMessageAbove(row) {
    const cells = Array()
    cells.push(document.createElement("td"))
    if (Object.keys(evalUIErrors).includes("__all__")) {
        cells.push(W(evalUIErrors['__all__'][0]['message'], "td"))
    } else {
        cells.push(document.createElement("td"))
    }
    cells.push(document.createElement("td"))
    if (Object.keys(evalUIErrors).includes("evaluator")) {
        cells.push(W(evalUIErrors['evaluator'][0]['message'], "td"))
    } else {
        cells.push(document.createElement("td"))
    }
    cells.push(document.createElement("td"))
    const errorRow = W(
        cells, "tr", "eval-input-row", "eval-error-message-row"
    )
    evalTableBody.insertBefore(errorRow, row)
    row.classList.add("eval-error-row")
}

const populateEvalRows = function(_event) {
    Object.keys(evaluations).forEach(function(hyp) {
        const row = gid(`${hyp}-eval-row`)
        if (Object.values(evalUIErrors).length > 0 && evalUIStatus.hyp === hyp) {
            insertErrorMessageAbove(row);
        }
        else if (evalUIStatus.hyp === hyp && evalUIStatus.success === true) {
            row.classList.add("eval-success-row")
        }
        evalRowFactory(hyp).forEach(cell => row.appendChild(cell))
        row.style.display = evaluations[hyp].critical === true ? 'table-row' : 'none'
    })
}
const togglePanoVisibility = function() {
    const display = (cameraRequest.value === 'navcam_panorama') ? 'block' : 'none';
    Array.from(panoOnlyInputs).forEach((input) => {input.style.display = display})
};
const toggleSliceVisibility = function() {
    const pano = cameraRequest.value === 'navcam_panorama'
    const slice = needs360.checked === false
    const display = pano && slice ? 'block' : 'none'
    Array.from(sliceInputs).forEach((input) => {input.style.display = display})
};

/**
 * @param {HTMLElement} row
 * @returns {function(Event|Element): void}
 */
const rowToggler = function(row) {
    return function(obj) {
        let source
        if (obj instanceof Event) {
            source = obj.target
        }
        else {
            source = obj
        }
        row.style.display = source.checked === true ? "table-row" : "none"
    }
}
const associateCriticalChecks = function(_event) {
    Object.values(criticalChecks).forEach(function(checkbox) {
        const hyp = checkbox.id.slice(0, 5)
        const row = gid(`${hyp}-eval-row`)
        const toggler = rowToggler(row)
        checkbox.addEventListener('change', toggler)
        toggler(checkbox)
    })
}

const populatePIDs = function(_event) {
    // TODO: lazy
    let nullSpacer = null
    Object.entries(verifications).forEach(entry => {
        const pid = entry[1] !== null ? entry[0] : entry[0] + ' (unverified)'
        const anchor = W(pid, "a", `${entry[1]}-link`)
        anchor.href = entry[0]
        pidHeader.appendChild(anchor)
        nullSpacer = W("", "div", "spacer-line")
        pidHeader.appendChild(nullSpacer)
    })
    pidHeader.removeChild(nullSpacer)
}

// TODO: take this all out and use the properties on the form
const populateReviewStatus = function(_event) {

    verificationStatusP.innerText = verificationStatusP.innerText + reqInfo['vcode']
    verificationStatusP.style.color = reqVColor[reqInfo['vcode']]
    if (reqInfo['evaluation_possible'] === false) {
        toggleButton.style.display = "none"
        return
    }
    const evalStatusP = W("evaluation: ", "p")
    const evalStatusDiv = W(evalStatusP, "div", "horizontal-div")
    evalStatusP.innerText = evalStatusP.innerText + reqInfo['ecode']
    evalStatusP.style.color = reqEColor[reqInfo['ecode']]
    reviewStatusDiv.appendChild(evalStatusDiv)
    evalStatusDiv.appendChild(toggleButton)
    if (evalTable.style.display === 'none') {
        toggleButton.innerText = "show evaluation interface"
    }
    else {
        toggleButton.innerText = "hide evaluation interface"
    }
}

const insertEvalFormState = function(id) {
    const form = gid(id)
    /**
     * @type {string[]}
     */
    const [insertHyps, state] = [[], {'critical': [], 'evals': []}]
    Array.from(criticalChecks).forEach(function(checkbox)
    {
        if (checkbox.checked !== true) {
            return
        }
        insertHyps.push(checkbox.id.slice(0, 5))
        state['critical'].push(checkbox.id)
    })
    const inputs = document.getElementsByClassName('eval-input-element')
    Array.from(inputs).forEach(function(input){
        if (!(insertHyps.includes(input.id.slice(0,5)))) {
            return
        }
        const stateObj = {'id': input.id}
        if (input.type === "checkbox") {
            stateObj["value"] = input.checked
        }
        else {
            stateObj['value'] = input.value
        }
        state['evals'].push(stateObj)
    })
    const stateInput = document.createElement('input')
    stateInput.name = "live_form_state"
    stateInput.value = JSON.stringify(state)
    stateInput.type = "hidden"
    form.appendChild(stateInput)
}

const updateFromLiveFormState = function(_event) {
    if (liveFormState.critical !== undefined) {
        liveFormState.critical.forEach(function(critCheckID){
            gid(critCheckID.replace("critical", 'relevant')).checked = true
            gid(
                critCheckID.replace("critical-check", 'eval-row')
            ).style.display = "table-row"
            const critCheck = gid(critCheckID)
            critCheck.checked = true
            critCheck.disabled = false
        })
    }
    if (liveFormState.evals === undefined) {
        return
    }
    liveFormState.evals.forEach(function({id, value}) {
        const element = gid(id)
        if (
            element instanceof HTMLInputElement
            && element.type === "checkbox"
        ) {
            element.checked = value
        } else {
            element.value = value
        }
    })
}

cameraRequest.addEventListener('change', togglePanoVisibility);
needs360.addEventListener('change', toggleSliceVisibility);
document.addEventListener("DOMContentLoaded", togglePanoVisibility)
document.addEventListener("DOMContentLoaded", toggleSliceVisibility)
document.addEventListener("DOMContentLoaded", populateHypotheses)
// if request has no associated products, review-related elements are not
// rendered at all
if (reviewPossible) {
    document.addEventListener("DOMContentLoaded", populateEvalRows)
    document.addEventListener("DOMContentLoaded", associateCriticalChecks)
    document.addEventListener("DOMContentLoaded", populatePIDs)
    document.addEventListener("DOMContentLoaded", populateReviewStatus)
    document.addEventListener("DOMContentLoaded", updateFromLiveFormState)
}
