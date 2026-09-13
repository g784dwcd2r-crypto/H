import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";
const base = process.env.SMOKE_BASE_URL || "http://localhost:3100";
const artifacts = path.resolve(process.env.SMOKE_ARTIFACT_DIR || ".browser-results/cited-research");
await mkdir(artifacts,{recursive:true});
const browser = await chromium.launch({headless:true,...(process.env.SMOKE_CHANNEL?{channel:process.env.SMOKE_CHANNEL}:{})});
const context = await browser.newContext({viewport:{width:1440,height:1000}});
const outsider = await browser.newContext();
const page = await context.newPage(); page.setDefaultTimeout(20000);
const errors=[]; page.on("pageerror",error=>errors.push(error.message));
async function check(name,action){await action(); console.log("PASS "+name);}
let version,run,project;
try {
  await check("Private research requires sign-in; synthetic source scope is explicit",async()=>{
    await page.goto(base+"/research/ask");
    await page.getByText("Research runs are private.",{exact:false}).waitFor();
    assert.equal(await page.getByRole("button",{name:"Ask with sources",exact:true}).isEnabled(),false);
    await page.goto(base+"/signin");
    await page.locator("input[type=email]").fill(`cited-${Date.now()}@example.test`);
    await page.getByRole("button",{name:"Email me a link"}).click();
    await page.getByRole("link",{name:"open the link"}).click(); await page.waitForURL(base+"/");
    const found=await context.request.get(base+"/api/research-assistant/search?q=disclosurecitedfixture&limit=20");
    assert.equal(found.status(),200);
    version=(await found.json()).results.find(r=>r.filename.includes("support")).version_id;
    const created=await context.request.post(base+"/api/projects",{data:{name:"Cited evidence acceptance"}});
    assert.equal(created.status(),201); project=(await created.json()).project;
  });
  await check("Typing another company and pressing Enter cannot submit the previous scope",async()=>{
    await page.goto(base+"/research/ask");
    await page.locator("#cited-company").fill("AAPL");
    await page.getByRole("option").filter({hasText:"Apple"}).waitFor();
    await page.locator("#cited-company").press("ArrowDown"); await page.locator("#cited-company").press("Enter");
    await page.locator("#research-question").fill("What does management say about liquidity?");
    await page.locator("#cited-company").fill("JPM"); await page.getByRole("option").first().waitFor();
    let posted=false; await page.route("**/api/research-assistant/runs",async route=>{posted=true;await route.fulfill({status:503,body:'{}'});});
    await page.locator("#cited-company").press("Enter");
    await page.getByRole("status").filter({hasText:"Select a company from the suggestions"}).waitFor();
    assert.equal(posted,false); assert.equal(await page.getByRole("list",{name:"Selected research companies"}).locator("li").count(),1);
    await page.unroute("**/api/research-assistant/runs");
  });
  await check("Source-scoped question returns exact inspectable projected evidence",async()=>{
    await page.goto(base+"/research/ask?version="+encodeURIComponent(version));
    await page.getByText("Synthetic demonstration.",{exact:true}).waitFor();
    await page.locator("#research-question").fill("What does the selected source say about revenue and liquidity?");
    const response=page.waitForResponse(r=>new URL(r.url()).pathname==="/api/research-assistant/runs"&&r.request().method()==="POST");
    await page.getByRole("button",{name:"Ask with sources",exact:true}).click(); run=await(await response).json();
    assert.equal(run.status,"completed"); assert.deepEqual(run.version_ids,[version]); assert.equal(run.provider.fixture,true);
    await page.locator(".cited-claim").getByRole("button",{name:/Inspect/}).click();
    const panel=page.getByRole("complementary",{name:"Exact source passage"}); await panel.locator(".source-match").waitFor();
    assert.match(await panel.locator("mark").innerText(),/Revenue was 1,200/);
    const p=run.passages[0]; assert.ok(p.projection_id);
    const projection=await(await context.request.get(base+"/api/research-assistant/projections/"+encodeURIComponent(p.projection_id))).json();
    assert.equal(Array.from(projection.text_content).slice(p.start,p.end).join(""),p.text);
    await page.evaluate(()=>window.scrollTo(0,0)); await page.screenshot({path:path.join(artifacts,"cited-exact-evidence.png"),fullPage:true});
  });
  await check("Exact source arithmetic saves and reopens under project authorization",async()=>{
    const panel=page.getByRole("complementary",{name:"Exact source passage"});
    await panel.getByText("Use source numbers in a calculation",{exact:true}).click();
    await panel.getByRole("button",{name:"Use 1,200",exact:true}).click(); await panel.getByRole("button",{name:"Use 1,000",exact:true}).click();
    await panel.getByRole("button",{name:"Close exact source passage"}).click();
    await page.getByLabel("Same unit for both operands",{exact:true}).fill("USD millions");
    await page.getByRole("button",{name:"Calculate exactly",exact:true}).click();
    await page.locator(".cited-calculations").getByText("20.0 %",{exact:true}).waitFor();
    await page.getByLabel("Save this result and evidence",{exact:true}).selectOption(project.id);
    await page.getByRole("button",{name:"Save research",exact:true}).click();
    await page.getByRole("status").filter({hasText:"Result, exact evidence and calculations saved"}).waitFor();
    await page.getByRole("link",{name:"Open project →",exact:true}).click();
    await page.getByRole("region",{name:"Saved cited research"}).getByRole("link",{name:run.question,exact:true}).click();
    await page.locator(".cited-calculations").getByText("20.0 %",{exact:true}).waitFor();
    await page.getByText("Synthetic demonstration.",{exact:true}).waitFor();
    assert.equal((await outsider.request.get(base+"/api/research-assistant/runs/"+run.id)).status(),401);
    await page.evaluate(()=>window.scrollTo(0,0)); await page.screenshot({path:path.join(artifacts,"cited-saved-calculation.png"),fullPage:true});
  });
  await check("Follow-up draft and locked scope survive source navigation and browser Back",async()=>{
    await page.getByRole("button",{name:"Ask a follow-up",exact:true}).click();
    await page.locator("#research-question").fill("Explain the source qualifications in my follow-up draft.");
    await page.locator(".cited-claim").getByRole("button",{name:/Inspect/}).click();
    await page.locator(".source-match").waitFor(); await page.getByRole("link",{name:"Open this source version",exact:true}).click();
    await page.getByRole("region",{name:"Extracted filing text"}).waitFor(); await page.goBack();
    await page.waitForFunction(()=>document.querySelector("#research-question")?.value==="Explain the source qualifications in my follow-up draft.");
    assert.equal(await page.getByLabel("Historical cutoff",{exact:true}).isDisabled(),true);
    await page.reload();
    await page.waitForFunction(()=>document.querySelector("#research-question")?.value==="Explain the source qualifications in my follow-up draft.");
    assert.equal(await page.getByLabel("Historical cutoff",{exact:true}).isDisabled(),true);
  });
  await check("Follow-ups keep exact scope and cutoff; unsupported answers are explicit",async()=>{
    await page.getByText("Scope fixed for follow-ups",{exact:true}).waitFor();
    assert.equal(await page.getByLabel("Historical cutoff",{exact:true}).isDisabled(),true);
    await page.locator("#research-question").fill("unsupported question about an unannounced future acquisition");
    const response=page.waitForResponse(r=>new URL(r.url()).pathname==="/api/research-assistant/runs"&&r.request().method()==="POST");
    await page.getByRole("button",{name:"Research follow-up",exact:true}).click(); const follow=await(await response).json();
    assert.equal(follow.status,"insufficient_evidence"); assert.equal(follow.parent_run_id,run.id);
    assert.deepEqual(follow.version_ids,run.version_ids); assert.equal(follow.as_of,run.as_of); assert.equal(follow.claims.length,0);
    await page.locator(".cited-run-heading").getByText("Insufficient evidence",{exact:true}).waitFor();
  });
  await check("Failed requests retain question and source selection and reuse one request key",async()=>{
    await page.goto(base+"/research/ask?version="+encodeURIComponent(version));
    await page.locator("#research-question").fill("Review revenue after a temporary network failure."); const keys=[];
    await page.route("**/api/research-assistant/runs",async route=>{keys.push(route.request().postDataJSON().idempotency_key); await route.fulfill({status:503,contentType:"application/json",body:JSON.stringify({error:"Simulated offline research service"})});});
    for(let i=0;i<2;i++){await page.getByRole("button",{name:"Ask with sources",exact:true}).click(); await page.getByRole("alert").filter({hasText:"Simulated offline"}).waitFor();}
    assert.equal(keys.length,2); assert.equal(keys[0],keys[1]);
    await page.reload(); await page.waitForFunction(()=>document.querySelector("#research-question")?.value==="Review revenue after a temporary network failure.");
    await page.getByRole("button",{name:"Ask with sources",exact:true}).click(); await page.getByRole("alert").filter({hasText:"Simulated offline"}).waitFor();
    assert.equal(keys.length,3); assert.equal(keys[0],keys[2]);
    assert.equal(await page.locator("#research-question").inputValue(),"Review revenue after a temporary network failure.");
    assert.equal(await page.getByRole("list",{name:"Selected document versions"}).locator("li").count(),1);
    await page.unroute("**/api/research-assistant/runs");
  });
  await check("Mobile evidence and reduced motion remain usable",async()=>{
    await page.setViewportSize({width:390,height:844}); await page.emulateMedia({reducedMotion:"reduce"});
    await page.goto(base+"/research/ask?run="+run.id);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
    await page.locator(".cited-claim").getByRole("button",{name:/Inspect/}).click(); await page.locator(".source-match").waitFor();
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
    await page.evaluate(()=>window.scrollTo(0,0)); await page.screenshot({path:path.join(artifacts,"cited-mobile-evidence.png"),fullPage:false});
    await page.getByRole("button",{name:"Close exact source passage"}).click(); assert.deepEqual(errors,[]);
  });
} catch(error){await page.evaluate(()=>window.scrollTo(0,0)); await page.screenshot({path:path.join(artifacts,"failure.png"),fullPage:true}).catch(()=>{}); throw error;}
finally{await browser.close();}
