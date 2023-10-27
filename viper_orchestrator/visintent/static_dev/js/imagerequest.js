// noinspection JSUnusedGlobalSymbols

/* shared DOM object references */
const evaluations = JSON.parse(gid("eval_json").textContent)
let evalUIErrors
if (gid("eval_error_json").textContent !== "") {
    evalUIErrors = JSON.parse(gid("eval_error_json").textContent)
}
else {
    evalUIErrors = ""
}
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
const evaluationPossible = evalTable !== null

const toggleEvalTable = function() {
    const isVisible = evalTable.style.display !== "none"
    evalTable.style.display = isVisible ? "none" : "table"
    toggleButton.innerText = isVisible ? "show evaluation" : "hide evaluation"
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
    const badCheck = checkFactory(hyp, "bad", status===true, "good")
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
const populateEvalRows = function(_event) {
    Object.keys(evaluations).forEach(function(hyp) {
        const row = gid(`${hyp}-eval-row`)
        if (evalUIErrors !== "" && evalUIHyp === hyp) {
            const cells = Array()
            cells.push(document.createElement("td"))
            console.log(evalUIErrors['__all__']['message'])
            if (Object.keys(evalUIErrors).includes("__all__")) {
                cells.push(W(evalUIErrors['__all__'][0]['message'],"td"))
            }
            else {
                cells.push(document.createElement("td"))
            }
            cells.push(document.createElement("td"))
            console.log('b')
            if (Object.keys(evalUIErrors).includes("evaluator")) {
                cells.push(W(evalUIErrors['evaluator'][0]['message'],"td"))
            }
            else {
                cells.push(document.createElement("td"))
            }
            cells.push(document.createElement("td"))
            const errorRow = W(
                cells, "tr", "eval-input-row", "eval-error-message-row"
            )
            console.log(errorRow)
            evalTableBody.insertBefore(errorRow, row)
            row.classList.add("eval-error-row")
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
 * @param {Event} event
 */
const updateEvalVisibility = function(event) {
    const hyp = event.explicitOriginalTarget.value
    const selected = event.explicitOriginalTarget.selected
    const row = gid(`${hyp}-eval-row`)
    const rowVisible = row.style.display !== "none"
    if (event.target === ldstCritical) {
        if (selected === true) {
            row.classList.add('critical-row')
        }
        else {
            row.classList.remove('critical-row')
        }
    }
    /* it's difficult to do this with just CSS because we
    make the critical options fully disappear when hypotheses are removed
    from primary select, hence the remainder of this function */
    if (rowVisible && ~selected) {
        row.style.display = "none"
    }
    else if (~rowVisible && selected && row.classList.contains('critical-row')) {
        row.style.display = "table-row"
    }
}

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
const prepEvalToggleButton = function(_event) {
    if (evalTable.style.display === 'none') {
        toggleButton.innerText = "show evaluation"
    }
    else {
        toggleButton.innerText = "hide evaluation"
    }
}

const populateEvalErrors = function(_event) {
    if (evalUIErrors === "") {
        return
    }
    evalTable.rows
}


cameraRequest.addEventListener('change', togglePanoVisibility);
needs360.addEventListener('change', toggleSliceVisibility);
document.addEventListener("DOMContentLoaded", togglePanoVisibility)
document.addEventListener("DOMContentLoaded", toggleSliceVisibility)
document.addEventListener("DOMContentLoaded", populateHypotheses)
// if request has no associated products, eval elements are not rendered at all
if (evaluationPossible) {
    document.addEventListener("DOMContentLoaded", populateEvalRows)
    document.addEventListener("DOMContentLoaded", associateCriticalChecks)
    document.addEventListener("DOMContentLoaded", prepEvalToggleButton)
    document.addEventListener("DOMContentLoaded", populateEvalErrors)
}