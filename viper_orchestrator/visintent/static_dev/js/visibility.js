/**
 * @type {HTMLTableElement[]}
 */
const tables = Array();

/**
 * @param {string|string[]|HTMLElement|HTMLElement[]} id
 * @param {?boolean} visible
 * @param {string} style
 */
const toggleVisibility = function(id, visible= null, style = "") {
    const elements = [];
    if (id instanceof Array) {
        id.forEach(i => elements.push(maybegid(i)))
    }
    else {
        elements.push(maybegid(id))
    }
    if (visible === true) {
        elements.forEach(e => e.style.display = style)
    }
    else if (visible === false) {
        elements.forEach(e => e.style.display = "none")
    }
    else if (visible === null) {
        elements.forEach(
            e => e.style.display = e.style.display === "none" ? style : "none"
        )
    }
    else {
        throw new Error(`invalid visibility directive ${visible}`)
    }

}

/**
 * @param {?HTMLElement} obj
 * @param {string} style
 * @param {string} prop
 */
const maybeStyle = function(obj, style='', prop = 'display') {
    if (obj !== null) {
        obj.style.setProperty(prop, style)
    }
}

/**
 * @param {HTMLTableElement} table
 * @returns {number}
 */
const nRows = function(table) {
    const body = Array.from(table.children).filter(c => c.tagName === 'TBODY')[0]
    if (body === undefined) {
        return 0
    }
    return body.children.length
}

/**
 * @param {HTMLTableElement} table
 * @param {boolean} visible
 */
const styleTable = function(table, visible) {
    const anchor = gid(`${table.id}-anchor`)
    const sorry = gid(`${table.id}-sorry`)
    const pageLinks = gid(`${table.id}-paginator-links`)
    const controls = gid(`${table.id}-controls`)
    const present = [table, pageLinks, controls].filter(e => e !== null)
    if (visible) {
        console.log(table.childElementCount)
        if (nRows(table) === 0) {
            maybeStyle(sorry)
            toggleVisibility(present, false)
        }
        else {
            maybeStyle(sorry, 'none')
            toggleVisibility(present, true)
        }
        maybeStyle(anchor, '#5fc5c6', 'color')
    }
    else {
        toggleVisibility(present, false)
        maybeStyle(sorry, 'none')
        maybeStyle(anchor, '#dee1e3', 'color')
    }
};

/**
 * @param {HTMLElement|string} obj
 * @returns {HTMLElement}
 */
const maybegid = function(obj) {
    if (obj instanceof Element) {
        return obj
    }
    return gid(obj)
}

/**
 * @param {HTMLInputElement} element
 */
const unCheck = function(element) {
    maybegid(element).checked = false
}

/**
 * @param {HTMLInputElement} target
 * @param {HTMLInputElement} reference
 */
const disableCheck = function(target, reference) {
    const element = maybegid(target)
    if (reference.checked !== true) {
        element.checked = false
        element.disabled = true
    }
    else {
        element.disabled = false
    }
}

const populateTableArray = function(_event) {
    Array.from(
        document.getElementsByClassName('toggle-table')
    ).forEach(element => tables.push(element))
}

/**
 * @param {string} post
 */
const revealTable = function(post) {
    tables.forEach(t => styleTable(t, t.id === `table-${post}`));
}

const revealDefault = function(_event) {
    revealTable(defaultTable)
}

const addCounts = function(_event) {
    tables.forEach(function(t) {
        const anchor = document.getElementById(`${t.id}-anchor`)
        let nRows = 0
        if (t.tBodies.length !== 0) {
            nRows = t.tBodies[0].childElementCount
        }
        anchor.innerText = anchor.innerText.concat(` (${nRows})`)
    })
}

document.addEventListener("DOMContentLoaded", populateTableArray)
