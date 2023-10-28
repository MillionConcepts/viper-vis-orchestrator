/**
 * @type {HTMLTableElement[]}
 */
const tables = Array();

/**
 * @param {HTMLTableElement} table
 * @param {boolean} visible
 */
const styleTable = function(table, visible) {
    const anchor = gid(`${table.id}-anchor`)
    const sorry = gid(`${table.id}-sorry`)
    const pageLinks = gid(`${table.id}-paginator-links`)
    if (visible) {
        if (table.childElementCount < 2) {
            table.style.display = 'none';
            sorry.style.display = ''
            if (pageLinks !== null) {
                pageLinks.style.display = 'none'
            }
        }
        else {
            table.style.display = ''
            sorry.style.display = 'none'
            if (pageLinks !== null) {
                pageLinks.style.display = ''
            }
        }
        anchor.style.color = '#5fc5c6';
    }
    else {
        table.style.display = 'none';
        sorry.style.display = 'none';
        anchor.style.color = '#dee1e3'
        if (pageLinks !== null) {
            pageLinks.style.display = 'none'
        }
    }
};

/**
 * @param {string} id
 * @param {?boolean} visible
 * @param {string} style
 */
const toggleVisibility = function(id, visible= null, style = "") {
    const elements = [];
    if (id instanceof Array) {
        id.forEach(i => elements.push(document.getElementById(i)))
    }
    else {
        elements.push(document.getElementById(id))
    }
    if (visible === true) {
        elements.forEach(element => element.style.display = style)
    }
    else if (visible === false) {
        elements.forEach(element => element.style.display = "none")
    }
    else if (visible === null) {
        elements.forEach(
            element =>
            element.style.display = element.style.display === "none" ? style : "none"
        )
    }
    else {
        throw `invalid visibility directive ${visible}`
    }
}

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
