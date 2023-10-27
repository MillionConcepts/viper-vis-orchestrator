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
const verifications = JSON.parse(gid("verification_json").textContent)


/**
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
const evaluations = JSON.parse(gid("eval_json").textContent)

/**
 *
 * @returns {any}
 */
const thing = function() {
    return evaluations
}

let evalUIErrors
if (gid("eval_error_json").textContent !== "") {
    evalUIErrors = JSON.parse(gid("eval_error_json").textContent)
}
else {
    evalUIErrors = ""
}
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
    textArea.name = name
    textArea.id = `${identifier}-notes`
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
    const field = gid("ldst-field-div")
    Object.entries(evaluations).forEach(function(entry){
        const hyp = entry[0]
        const eval = entry[1]
        const relevant = eval['relevant']
        const critical = eval['critical']
        const ldstCheck = checkFactory(
            hyp, 'relevant', relevant===true, "critical", true, true
        )
        const critCheck = checkFactory(
            hyp, 'critical', critical===true, null, true
        )
        critCheck.disabled = !relevant
        const row = W([...L(ldstCheck, hyp), ...L(critCheck, "critical?")], "div")
        field.appendChild(row)
    })
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
        if (Object.values(evalUIErrors).length > 0 && evalUIHyp === hyp) {
            insertErrorMessageAbove(row);
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
    Object.entries(verifications).forEach(entry => {
        const pid = entry[1] !== null ? entry[0] : entry[0] + ' (unverified)'
        const anchor = W(pid, "a", `${entry[1]}-link`)
        anchor.href = entry[0]
        pidHeader.appendChild(anchor)
    })
    Array.from(pidHeader.children).slice(-1)[0].classList.add('rightmost-status-link')
}

// TODO: take this all out and use the properties on the form
const populateReviewStatus = function(_event) {
    let [evaluatable, verText, verColor] = [true, null, null]
    if (Object.values(verifications).every(v => v === null)) {
        [evaluatable, verText, verColor] = [false, " none", "#D79A00"]
    }
    else if (Object.values(verifications).some(v => v === null)) {
        [evaluatable, verText, verColor] = [false, " partial", "#D79A00"]
    }
    else if (Object.values(verifications).every(v => v === true)) {
        [verText, verColor] = [" full (passed)", "#00CC11"]
    }
    else if (Object.values(verifications).every(v => v === false)) {
        [verText, verColor] = [" full (failed)", "#BB2222"]
    }
    else {
        [verText, verColor] = [" full (mixed)", "lightskyblue"]
    }
    verificationStatusP.innerText = verificationStatusP.innerText + verText
    verificationStatusP.style.color = verColor
    if (evaluatable === false) {
        return
    }
    const evalStatusP = W("evaluation: ", "p")
    const evalStatusDiv = W(evalStatusP, "div", "horizontal-div")
    const evaluated = Object.values(evaluations).map(
        v => v['critical'] !== true || v['evaluation'] !== null
    )
    let [evalText, evalColor] = [null, null]
    if (Object.values(evaluations).every(v => v['critical'] !== true)) {
        [evalText, evalColor, evaluatable] = [
            "no critical hypotheses", "lightskyblue", false
        ]
    }
    if (evaluated.every(e => e === true)) {
        [evalText, evalColor] = [" full", "#00CC11"]
    }
    else if (evaluated.some(e => e === true)) {
        [evalText, evalColor] = [" partial", "#D79A00"]
    }
    else {
        [evalText, evalColor] = [" none", "#D79A00"]
    }
    evalStatusP.innerText = evalStatusP.innerText + evalText
    evalStatusP.style.color = evalColor
    reviewStatusDiv.appendChild(evalStatusDiv)
    evalStatusDiv.appendChild(toggleButton)
    if (evalTable.style.display === 'none') {
        toggleButton.innerText = "show evaluation interface"
    }
    else {
        toggleButton.innerText = "hide evaluation interface"
    }



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
}

