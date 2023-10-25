const tables = Array.from(document.getElementsByClassName('toggle-table'));
const styleTable = function(table, visible) {
    const anchor = document.getElementById(`${table.id}-anchor`)
    const sorry = document.getElementById(`${table.id}-sorry`)
    if (visible) {
        if (table.childElementCount < 2) {
            table.style.display = 'none';
            sorry.style.display = 'inherit'
        }
        else {
            table.style.display = 'inherit'
            sorry.style.display = 'none'
        }
        anchor.style.color = '#5fc5c6';
    }
    else {
        table.style.display = 'none';
        sorry.style.display = 'none';
        anchor.style.color = '#dee1e3'
    }
};
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
const toggleVisibility = function(id, visible= null, style = "inherit") {
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

const turnOff = function(element) {
    element.checked = false
}