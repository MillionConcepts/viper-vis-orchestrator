/**
 * @param {string} nodeID
 * @param {string[]} attributes
 * @param {(string|number|boolean)[]} values
 * @constructor
 */
const targetSpec = function(nodeID, attributes=[], values=[]) {
    this.nodeID = nodeID
    this.attributes = attributes
    this.values = values
}

/**
 *
 * @param {targetSpec[][]} targets
 * @returns {number}
 */
function getEqualLength(targets) {
    const lengths = targets.map(t => t.length)
    if (lengths.every(l => l === 0)) {
        return 0
    }
    if (lengths.some(l => l !== lengths[0])) {
        throw new Error("all target arrays must have the same length")
    }
    return lengths[0];
}

/**
 * @param {targetSpec} target
 */
const populateFromSpec = function(target) {
    const node = gid(target.nodeID)
    for (let i = 0; i < target.attributes.length; i++) {
        node.setAttribute(target.attributes[i], target.values[i])
    }
}

/**
 * @param {targetSpec[]} targets
 */
const populatePage = function(targets) {
    targets.forEach(t => populateFromSpec(t))
}

/**
 * @param {?number} i
 * @param {string} parentID
 * @param {number} maximum
 */
const revealAround = function(i, parentID, maximum) {
    if (i === null) {
        return
    }
    const children = Array.from(gid(parentID).children)
    let nRevealed = 0
    for (let j = 0; j < children.length; j++) {
        if (i - j > maximum / 2 || nRevealed > maximum) {
            children[j].style.display = "none"
        }
        else {
            children[j].style.display = ""
            nRevealed++
        }
    }
}

/**
 * @param {targetSpec[]} page
 * @param {boolean} on
 */
const showPage = function(page, on = false) {
    page.forEach(function(p){
        gid(p['nodeID']).style.display = on ? "" : "none"
    })
}

/**
 * @param {targetSpec[][]} targetSet
 * @param {number} nPages
 * @param {number} pageSize
 * @returns {targetSpec[][]}
 */
const splitIntoPages = function(targetSet, nPages, pageSize) {
    const pageArray = []
    for (let i = 0; i < targetSet.length; i++) {
        let [absolute, targets] = [0, targetSet[i]]
        for (let i = 0; i < nPages; i++) {
            if (pageArray[i] === undefined) {
                pageArray.push([])
            }
            let page = pageArray[i]
            let relative = 0
            while (absolute < targets.length && relative < pageSize) {
                page.push(targets[absolute])
                absolute++
                relative++
            }
        }
    }
    return pageArray
}

/**
 * @param {Paginator} paginator
 */
const populateLinkDiv = function(paginator) {
    const div = gid(paginator.linkDiv)
    const navLeft = W("<", "a")
    navLeft.id = `${paginator.linkDiv}-link-left`
    navLeft.onclick = () => paginator.reveal(
        Math.max(paginator.currentPage - 1, 0)
    )
    div.appendChild(navLeft)
    for (let i = 0; i < paginator.nPages; i++) {
        let link = W(`${i}`, "a", "paginator-link")
        link.onclick = () => paginator.reveal(i)
        link.id = `${paginator.linkDiv}-link-${i}`
        div.appendChild(link)
    }
    const navRight = W(">", "a")
    navRight.id = `${paginator.linkDiv}-link-right`
    navRight.onclick = () => paginator.reveal(
        Math.min(paginator.currentPage + 1, paginator.nPages)
    )
    div.appendChild(navRight)
}

/**
 * @param {targetSpec[][]} targets
 * @param {number} pageSize
 * @param {string} linkDiv
 * @param {number} maxLinks
 * @param {?number} currentPage
 * @constructor
 */
class Paginator {
    constructor(
        targets,
        linkDiv,
        pageSize = 8,
        maxLinks = 10,
        currentPage = 0
    ) {
        this.length = getEqualLength(targets);
        this.pageSize = pageSize
        this.nPages = Math.ceil(this.length / this.pageSize)
        this.targets = targets
        this.currentPage = currentPage
        this.linkDiv = linkDiv
        this.maxLinks = maxLinks
        this.pages = splitIntoPages(this.targets, this.nPages, this.pageSize)
        this.pagesPopulated = Array()
    }

    populate() {
        if (!this.pagesPopulated.includes(this.currentPage)) {
            populatePage(this.pages[this.currentPage])
            this.pagesPopulated.push(this.currentPage)
        }
    }

    /**
     * @param {number} pageNumber
     */
    linkNode(pageNumber) {
        return gid(`${this.linkDiv}-link-${pageNumber}`)
    }

    /**
     * @param {number} pageNumber
     */
    reveal(pageNumber) {
        if (
            this.currentPage === pageNumber
            && this.pagesPopulated.includes(pageNumber)
        ) {
            return
        }
        if (this.nPages > 1) {
            for (let t of [this.currentPage, 'left', 'right']) {
                gid(
                    `${this.linkDiv}-link-${t}`
                ).classList.remove('inactive-paginator-link')
            }
        }
        this.currentPage = pageNumber
        this.populate()
        for (let i = 0; i < this.nPages; i++) {
            showPage(this.pages[i], i === this.currentPage)
        }
        revealAround(this.currentPage, this.linkDiv, this.maxLinks)
        if (this.nPages === 1) {
            return
        }
        this.linkNode(this.currentPage).classList.add('inactive-paginator-link')
        if (this.currentPage === this.nPages - 1) {
            gid(`${this.linkDiv}-link-right`).classList.add('inactive-paginator-link')
        }
        else if (this.currentPage === 0) {
            gid(`${this.linkDiv}-link-left`).classList.add('inactive-paginator-link')
            }
        }

    init() {
        if (this.nPages !== 1) {
            populateLinkDiv(this)
        }
        this.reveal(this.currentPage)
    }
}
