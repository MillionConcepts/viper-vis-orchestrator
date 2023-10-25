// noinspection JSUnusedGlobalSymbols

/**
 * @param {string} id
 * @returns Element
 */
const gid = (id) => document.getElementById(id)

/**
 * @param {*} obj
 * @returns {Array|*[]}
 */
const listify = function(obj) {
    if (obj instanceof Array) {
        return obj
    }
    return [obj]
}

/**
 * @param {string[]|HTMLElement[]|string|HTMLElement} content
 * @param {string|HTMLElement} wrapper
 * @param {...string} classes
 * @returns {HTMLElement}
 */
const W = function(content, wrapper, ...classes) {
    content = listify(content)
    if (typeof(wrapper[0]) === "string") {
        wrapper = document.createElement(wrapper)
    }
    if (classes.length > 0) {
        wrapper.classList.add(...classes)
    }
    if (typeof(content[0]) === "string") {
        content.forEach(
            t => wrapper.innerText = wrapper.innerText + t
        )
    }
    else {
        content.forEach(e => wrapper.appendChild(e))
    }
    return wrapper
}

/**
 * @param {string} form_id
 * @param {...HTMLElement} nodes
 */
const addForm = function(form_id, ...nodes) {
    const formable = ["INPUT", "TEXTAREA", "BUTTON", "SELECT"]
    nodes.forEach(function(node){
        if (formable.includes(node.nodeName)) {
            node.setAttribute("form", form_id)
        }
        addForm(form_id, ...Object.values(node.children))
    })
}

/**
 * @param {HTMLElement} element
 * @param {?string} text
 * @param {boolean} wrap
 * @returns {HTMLElement[]}
 */
const L = function(element, text=null, wrap=false) {
    const label = document.createElement('label')
    label.id = `${element.id}-label`
    label.htmlFor = element.id
    label.innerText = text === null ? "" : text
    if (wrap === true) {
        label.appendChild(element)
        return [label]
    }
    return [label, element]
}