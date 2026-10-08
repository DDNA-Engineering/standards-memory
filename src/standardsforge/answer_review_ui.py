"""Local human review packet, separate from evidence queries and approvals."""
from __future__ import annotations

import base64
import hashlib
import html
import json
from pathlib import Path
from typing import Any

from .answer_benchmark import validate_submission
from .errors import require
from .reference_bindings import _evidence

STYLE = """
*{box-sizing:border-box}body{margin:0;background:#f5f3ee;color:#17242c;font:16px/1.6 system-ui,sans-serif}
main{max-width:1150px;margin:auto;padding:40px 24px 100px}h1{font-size:36px;line-height:1.15}h2{font-size:22px}
.eyebrow{font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#47625c}article{background:white;border:1px solid #d9ded9;border-radius:12px;padding:28px;margin:26px 0}
.answer{background:#e9f1ed;border-left:4px solid #466d5a;padding:16px 22px}.columns{display:grid;grid-template-columns:1fr 1fr;gap:24px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f6f2;padding:16px;font:13px/1.55 ui-monospace,monospace;max-height:500px;overflow:auto}
details{margin:12px 0}summary{cursor:pointer;font-weight:600}code{font-size:12px;overflow-wrap:anywhere}label{display:block;margin:16px 0 4px}
input,select,textarea,button{font:inherit}input,select,textarea{width:100%;padding:9px;border:1px solid #a3b2ac;border-radius:5px;background:#fff}textarea{min-height:70px}
button{cursor:pointer;border:0;border-radius:5px;background:#204f42;color:white;padding:10px 16px;margin:8px 8px 0 0}.secondary{background:#e1e8e4;color:#203c32}
nav{position:sticky;top:0;z-index:1;background:#172f29;color:white;padding:12px 24px;display:flex;align-items:center;gap:22px;flex-wrap:wrap}nav span{margin-right:auto}
.note{color:#566762;font-size:14px}.criterion{border-top:1px solid #e3e7e3;padding:12px 0}.badge{font-size:12px;background:#e5e8df;padding:4px 9px;border-radius:20px}
@media(max-width:850px){.columns{grid-template-columns:1fr}main{padding:20px}article{padding:20px}}
"""

SCRIPT = r"""
const data=JSON.parse(document.getElementById('review-data').textContent);
const cards=[...document.querySelectorAll('article')];
function update(){let n=cards.filter(c=>[...c.querySelectorAll('select')].every(s=>s.value)).length;
document.getElementById('progress').textContent=`${n} of ${cards.length} answers reviewed`;}
document.querySelectorAll('select').forEach(s=>s.addEventListener('change',update));
document.querySelectorAll('[data-accept]').forEach(b=>b.addEventListener('click',()=>{
 const card=b.closest('article');card.querySelector('[data-answer-verdict]').value='supported';
 card.querySelectorAll('[data-criterion]').forEach(s=>s.value='pass');
 card.querySelector('[data-rationale]').value='I reviewed the answer against the displayed exact source evidence and all listed criteria.';update();}));
function canonical(v){if(Array.isArray(v))return '['+v.map(canonical).join(',')+']';
 if(v!==null&&typeof v==='object')return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';return JSON.stringify(v);}
async function hash(v){let h=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical(v)));return [...new Uint8Array(h)].map(x=>x.toString(16).padStart(2,'0')).join('');}
document.getElementById('export').addEventListener('click',async()=>{try{
 const identity=document.getElementById('reviewer').value.trim();if(!identity)throw Error('Enter your reviewer name or ID.');
 if([data.suite.suite.author_identity,data.submission.submission.respondent_identity].some(i=>i.trim().toLowerCase()===identity.toLowerCase()))throw Error('Use your own reviewer identity, separate from the agent author.');
 const reviews=cards.map(card=>{let verdict=card.querySelector('[data-answer-verdict]').value;
 let rationale=card.querySelector('[data-rationale]').value.trim();if(!verdict||!rationale)throw Error('Select a verdict and enter a rationale for every answer.');
 let criteria=[...card.querySelectorAll('[data-criterion]')].map(s=>{if(!s.value)throw Error('Judge every listed criterion.');
 let note=card.querySelector(`[data-note="${s.dataset.criterion}"]`).value.trim();
 if(s.value!=='pass'&&!note)throw Error('Explain each failed or unassessed criterion.');
 return {criterion_id:s.dataset.criterion,verdict:s.value,rationale:note||'Confirmed against the displayed source and proposed answer.'};});
 return {case_id:card.dataset.case,answer_verdict:verdict,rationale,criteria};});
 const body={suite_sha256:data.suite.suite_sha256,submission_sha256:data.submission.submission_sha256,
 reviewer:{identity,kind:'human',reviewed_at:new Date().toISOString(),method:'Human review of the frozen local questions, proposed answers, criteria and exact source evidence.',independence_claim:'separate_reviewer'},case_reviews:reviews};
 const artifact={schema_version:'0.1.0',adjudication:body,adjudication_sha256:await hash(body)};
 const url=URL.createObjectURL(new Blob([JSON.stringify(artifact,null,2)+'\n'],{type:'application/json'}));
 const a=document.createElement('a');a.href=url;a.download='answer-adjudication.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 document.getElementById('message').textContent='Review exported locally. Nothing has been published or granted approval.';
 }catch(e){document.getElementById('message').textContent=e.message;}});update();
"""


def export_answer_review(service: Any, principal: str, suite: Any, submission: Any, destination: str | Path) -> dict[str, Any]:
    validate_submission(suite, submission)
    require(service.store.read_only, "invalid_answer_benchmark", "Review export requires an existing read-only store.")
    path = Path(destination)
    require(not path.exists(), "output_exists", "Review export refuses to overwrite an existing file.")
    state = service.store.cache_state(principal)
    esc = html.escape
    answers = {a["case_id"]: a for a in submission["submission"]["answers"]}
    cards, packages = [], set()
    for index, case in enumerate(suite["suite"]["cases"], 1):
        answer = answers[case["case_id"]]
        evidence = []
        for selector in case["evidence"]:
            packet = _evidence(service, selector, principal)
            packages.add(selector["package_digest"])
            for record in packet["evidence"]:
                evidence.append(f'<details open><summary>{esc(packet["package"]["identifier"])} · {esc(record["clause_reference"])} · physical page {record["citation"]["page"]}</summary>'
                                f'<pre>{esc(record["text"])}</pre><div class="note">{esc(record["derivation"]["review_status"])}</div>'
                                f'<details><summary>Exact evidence identity</summary><code>{esc(json.dumps({"package_digest":packet["package"]["package_digest"],"edition_id":packet["package"]["edition_id"],"record_id":record["record_id"],"citation":record["citation"]},ensure_ascii=False))}</code></details></details>')
        criteria = []
        for criterion in case["criteria"]:
            key = esc(criterion["criterion_id"], quote=True)
            criteria.append(f'<div class="criterion"><label>{esc(criterion["requirement"])}</label><select data-criterion="{key}"><option value="">Unreviewed</option><option value="pass">Pass</option><option value="fail">Needs correction</option><option value="unable_to_assess">Unable to assess</option></select><input data-note="{key}" aria-label="Criterion review note" placeholder="Reason (required for correction or unable to assess)"></div>')
        cards.append(f'<article data-case="{esc(case["case_id"],quote=True)}"><span class="badge">Question {index} / {len(answers)}</span><h2>{esc(case["question"])}</h2>'
                     f'<div class="columns"><section><p class="eyebrow">Proposed answer — agent authored</p><div class="answer">{esc(answer["text"])}</div><h3>Review criteria</h3>{"".join(criteria)}'
                     '<label>Does the whole answer stay within the evidence?</label><select data-answer-verdict><option value="">Unreviewed</option><option value="supported">Supported</option><option value="contradicted">Contradicted</option><option value="insufficient_evidence">Insufficient evidence</option><option value="unable_to_assess">Unable to assess</option></select>'
                     '<label>Your rationale or correction</label><textarea data-rationale></textarea><button data-accept class="secondary">Accept answer and listed criteria</button></section>'
                     f'<section><p class="eyebrow">Exact source and required context</p>{"".join(evidence)}</section></div></article>')
    data = json.dumps({"suite": suite, "submission": submission}, ensure_ascii=False).replace('<', '\\u003c').replace('&', '\\u0026')
    def csp_hash(value: str) -> str:
        return base64.b64encode(hashlib.sha256(value.encode('utf-8')).digest()).decode('ascii')
    csp = f"default-src 'none'; script-src 'sha256-{csp_hash(SCRIPT)}'; style-src 'sha256-{csp_hash(STYLE)}'; base-uri 'none'; form-action 'none'; object-src 'none'; connect-src 'none'"
    page = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta http-equiv="Content-Security-Policy" content="{esc(csp,quote=True)}"><title>StandardsForge — Answer review</title><style>{STYLE}</style></head><body>'
            '<nav><strong>StandardsForge</strong><span id="progress"></span><button id="export">Export completed review</button></nav><main>'
            '<p class="eyebrow">Source-grounded answer qualification</p><h1>Your independent review</h1>'
            '<p>Read each proposed answer against the exact source at right. Check conditions, exceptions, edition choices, and missing context. '
            'Mark corrections wherever needed. All judgments start unreviewed. This is answer-quality review, not engineering approval or project applicability.</p>'
            '<p class="note">The agent authored these selected questions and answers after source inspection. Your adjudication is separate; this is not a blinded holdout or a corpus-wide accuracy estimate. Extracted typography is preserved. No data is sent from this page. Unsaved form choices are lost on reload.</p>'
            f'<details><summary>Frozen artifact identities</summary><code>Suite: {suite["suite_sha256"]}<br>Submission: {submission["submission_sha256"]}</code></details>'
            '<label for="reviewer">Your name or reviewer ID</label><input id="reviewer" autocomplete="name" placeholder="Enter your reviewer identity"><p id="message" role="status"></p>'
            + ''.join(cards) + f'<script type="application/json" id="review-data">{data}</script><script>{SCRIPT}</script></main></body></html>')
    for pin in sorted(packages):
        service.store.authorized_package(principal, pin)
    require(service.store.cache_state(principal) == state, "authorization_changed", "Authorization changed during review export.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(page)
    return {"operation": "export_answer_review", "path": str(path.resolve()), "cases": len(cards),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "review_status": "awaiting_human_review"}
