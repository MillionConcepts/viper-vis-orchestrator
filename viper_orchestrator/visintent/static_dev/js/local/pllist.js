// noinspection JSUnusedGlobalSymbols


const paginators = {}

/**
 * @type {protectedListRecord[]}
 */
const records = JSON.parse(gid('pl_json').innerText)

const PLStatusStyle = {
    "fulfilled": "#00CC11",
    "superseded": "#BB2222",
    "pending": "#D79A00",
}

const CCULinkCellFactory = function(pid, pl_url) {
    const [vCell, lCell] = [pid, "edit"].map(e => W(e, "a"))
    vCell.href = pid
    lCell.href = pl_url
    return [vCell, lCell]

}
const CCURowFactory = function({image_id, pid, request_time, pl_url}) {
    const [vCell, lCell] = CCULinkCellFactory(pid, pl_url)
    const cells = [String(image_id), vCell, request_time, lCell].map(e => W(e, "td"))
    return W(cells, "tr", "ccu-table-row")
}

const logRowFactory = function (
    {image_id, request_time, rationale, pl_url, has_lossless, superseded, pid}
) {
    const [vCell, lCell] = CCULinkCellFactory(pid, pl_url)
    let status
    if (has_lossless === true) {
        status = "fulfilled"
    }
    else if (superseded === true) {
        status = "superseded"
    }
    else {
        status = "pending"
    }
    const sCell = W(status, "p")
    sCell.style.color = PLStatusStyle[status]
    const cells = [String(image_id), vCell, request_time, sCell, rationale, lCell].map(
        e => W(e, "td")
    )
    return W(cells, "tr", "pl-log-table-row")
}

const buildTables = function(_event) {
    const logFrag = new DocumentFragment
    const CCUFrags = {0: new DocumentFragment, 1: new DocumentFragment}
    records.forEach(function(record){
        if (!(record.superseded || record.has_lossless)) {
            const CCURow = CCURowFactory(record)
            const CCURowNum = CCUFrags[record.ccu].childElementCount
            CCURow.id = `ccu-${record.ccu}-row-${CCURowNum}`
            CCUFrags[record.ccu].appendChild(CCURow)
        }
        const logRow = logRowFactory(record)
        logRow.id = `log-row-${logFrag.childElementCount}`
        logFrag.appendChild(logRow)
    })
    gid('table-ccu-0-body').appendChild(CCUFrags[0])
    gid('table-ccu-1-body').appendChild(CCUFrags[1])
    gid('table-pl-log-body').appendChild(logFrag)
}

const nullableTables = document.getElementsByClassName('nullable-table')

const nullifyEmptyTables = function(_event) {
    Array.from(nullableTables).forEach(
      t => styleTable(t, t.tBodies[0].childElementCount > 0)
    )
}