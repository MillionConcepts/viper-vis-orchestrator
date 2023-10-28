// noinspection JSUnusedGlobalSymbols

/**
 * @param {string} id
 * @returns HTMLElement
 */
const gid = (id) => document.getElementById(id)

/**
 * @param {string|HTMLElement} obj
 * @returns {HTMLElement}
 */
const maybeGid = function(obj) {
    if (typeof(obj) === "string") {
        return gid(obj)
    }
    else if (obj instanceof HTMLElement) {
        return obj
    }
    throw new Error("unknown object type")
}

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
 * @param {string[]|HTMLElement[]|H[]|string|HTMLElement|H} content
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

/**
 *
 * @param {function(...*):* } func
 * @param {*} args
 * @param {?number} offset
 * @returns {function(...*):*}
 */
const partial = function(func, args, offset=null) {
    const boundArgs = listify(args)
    /**
     * @type *[]
     */
    const shift = offset === null ? 0 : offset
    return function(...args) {
        const finalArgs = []
        const nExpected = args.length + boundArgs.length
        let [boundPointer, argPointer] = [0, 0]
        for (let i = 0; i < nExpected; i++) {
            if (i <= shift && boundPointer < boundArgs.length) {
                finalArgs.push(boundArgs[boundPointer])
                boundPointer++
            }
            else {
                finalArgs.push(args[argPointer])
                argPointer++
            }
        }
        return func(...finalArgs)
    }
}

/**
 * sorts an Object into an Array of entries. note that the property
 * collection of an object is unsorted, so you cannot insert keys in order
 * to produce a 'sorted Object'.
 * @param {Object} obj
 * @param {function([string, *], [string, *], ...):{number}} compareFn
 * @param {...*} sortArgs
 * @returns {[string, *][]}
 */
const objsort = function(obj, compareFn, ...sortArgs) {
    const boundComp = partial(compareFn, sortArgs, 2)
    return Array.from(Object.entries(obj)).sort(boundComp)
}