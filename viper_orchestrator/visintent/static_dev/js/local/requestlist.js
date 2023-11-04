/**
 * @type {reqInfoRecord[]}
 */
const reqInfo = JSON.parse(gid('request_json').innerText)


/**
 * @param {reqInfoRecord} req
 * @returns {HTMLTableRowElement}
 */
const reqRowFactory = function(req) {
    const {req_id, edit_url, title, justification, rec_ids, vcode, ecode, request_time} = req
    const idCell = W(String(req_id), "a")
    idCell.href = edit_url + "&editing=false"
    const tCell = W(title, "a")
    tCell.href = edit_url + "&editing=false"
    const vCell = W(vcode, "p")
    vCell.style.color = reqVColor[vcode]
    const eCell = W(ecode, "p")
    eCell.style.color = reqEColor[ecode]
    const cells = [
        idCell, tCell, justification, String(rec_ids.length), vCell, eCell, request_time
    ].map(e => W(e, "td"))
    return W(cells, "tr")
}


const buildRequestTable = function(_event) {
    const [frags, rowNums] = [{}, {}]
    tables.forEach(function({id}){
       frags[id.replace('table-', '')] = new DocumentFragment
       rowNums[id.replace('table-', '')] = 0
    })
    reqInfo.forEach(
        function(req) {
            const [trs, tra] = [reqRowFactory(req), reqRowFactory(req)]
            trs.id = `${req.status}-row-${rowNums[req.status]}`
            tra.id = `all-row-${rowNums['all']}`
            rowNums[req.status] = rowNums[req.status] + 1
            rowNums["all"] = rowNums["all"] + 1
            frags[req.status].appendChild(trs)
            frags["all"].appendChild(tra)
        })
    tables.forEach(
        t => gid(t.id + "-body").appendChild(frags[t.id.replace('table-', '')])
    )
}