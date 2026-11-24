const {chromium}=require("playwright");
const assert=require("node:assert/strict");
const staffToken=process.env.DEMO_EMPLOYEE_TOKEN;
const year=new Date().getFullYear()+1;
async function discovery(page) {
  await page.goto("http://localhost:3000");
  await page.getByRole("link",{name:"Open rental desk"}).click();
  await page.getByText(/Offline grammar/).waitFor();
  await page.getByLabel("Describe your rental").fill("Tempe sedan from "+year+"-03-01 through "+year+"-03-08 under $950 monthly");
  await page.getByRole("button",{name:"Find rentals"}).click();
  await page.getByRole("heading",{name:/Toyota Camry/}).waitFor();
}
async function ask(page,message,visible) {
  await page.getByLabel("Ask about these results").fill(message);
  await page.getByRole("button",{name:"Ask",exact:true}).click();
  await page.locator("p[aria-live]").filter({hasText:visible}).waitFor();
}
async function pending(page) {
  await page.getByRole("button",{name:/Accept these terms/}).click();
  await page.locator("strong").filter({hasText:"pending ·"}).waitFor();
}
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||undefined,args:["--no-sandbox"]});
 try {
  const desktop=await browser.newPage();
  const mobile=await browser.newPage({viewport:{width:390,height:844},isMobile:true});
  for(const page of [desktop,mobile]) {
    await discovery(page);
    await ask(page,"Keep the same budget but switch to an SUV","Search updated");
    await page.getByRole("heading",{name:/2. 2017 Toyota/}).waitFor();
    await ask(page,"Compare the first two","Toyota RAV4");
    await ask(page,"Quote that vehicle","select a vehicle");
    assert.equal(await page.getByRole("button",{name:/Accept these terms/}).count(),0);
    await ask(page,"Don't quote the first one","No action taken");
    assert.equal(await page.getByRole("button",{name:/Accept these terms/}).count(),0);
    await ask(page,"Select the first vehicle","Selected 2018 Nissan");
    await ask(page,"Where do I collect the keys?",/pickup desk|ask staff/);
    await ask(page,"What is the pickup procedure?","pickup desk");
    await ask(page,"Would my pet earn air miles?","ask staff");
    await ask(page,"Where do we meet for pickup, and can I come after midnight?","pickup desk");
    assert.match(await page.locator("p[aria-live]").innerText(),/ask staff/i);
    await ask(page,"Quote that vehicle","vehicle 6");
    await pending(page);
  }
  await desktop.getByText("Staff review",{exact:true}).click();
  await desktop.getByLabel("Individual employee token").fill(staffToken);
  await desktop.getByRole("button",{name:"Load requests"}).click();
  const ownId=(await desktop.locator("strong").filter({hasText:"pending ·"}).innerText()).split(" · ")[1];
  const staffRow=(id)=>desktop.locator("details article").filter({hasText:id});
  await staffRow(ownId).getByRole("button",{name:"approve",exact:true}).click();
  await desktop.locator("strong").filter({hasText:"confirmed ·"}).waitFor();
  const mobileId=(await mobile.locator("strong").filter({hasText:"pending ·"}).innerText()).split(" · ")[1];
  await staffRow(mobileId).getByRole("button",{name:"approve",exact:true}).click();
  await desktop.getByRole("alert").filter({hasText:/already reserved/}).waitFor();
  await desktop.getByLabel("New return date").fill(year+"-03-10");
  await desktop.getByRole("button",{name:"Quote an extension"}).click();
  await pending(desktop);
  const extensionId=(await desktop.locator("strong").filter({hasText:"pending ·"}).innerText()).split(" · ")[1];
  await desktop.getByRole("button",{name:"Load requests"}).click();
  await staffRow(extensionId).getByRole("button",{name:"approve",exact:true}).click();
  await desktop.locator("strong").filter({hasText:"extended ·"}).waitFor();
  await desktop.reload();
  await desktop.locator("strong").filter({hasText:"confirmed · "+extensionId}).waitFor();
  await desktop.getByRole("button",{name:"Clear chat history"}).click();
  await desktop.getByText("Chat cleared. Your rental records remain available.").waitFor();
  await desktop.locator("strong").filter({hasText:"confirmed · "+extensionId}).waitFor();
  await desktop.getByText("Staff review",{exact:true}).click();
  await desktop.getByLabel("Individual employee token").fill(staffToken);
  await desktop.getByRole("button",{name:"Load requests"}).click();
  await staffRow(extensionId).getByRole("button",{name:"cancel",exact:true}).click();
  await desktop.locator("strong").filter({hasText:"cancelled · "+extensionId}).waitFor();
  await ask(mobile,"Change my budget to $1 monthly","No exact matches");
  assert.equal(await mobile.getByRole("button",{name:"Select vehicle",exact:true}).count(),0);
  await ask(mobile,"Raise my cap to $950 monthly","Search updated");
  await ask(mobile,"Keep my budget and require seven seats","No exact matches");
  await mobile.reload();
  await mobile.getByText("No exact matches for the current search.").waitFor();
  assert.equal(await mobile.getByLabel("Maximum USD per selected period").inputValue(),"950");
  assert.equal(await mobile.getByLabel("Minimum seats").inputValue(),"7");
  await ask(mobile,"Raise my cap to $1,200 monthly","Search updated");
  await ask(mobile,"Under seven seats","minimum seat count");
  await ask(mobile,"When does my quote expire?","Quotes expire in fifteen minutes");
  await ask(mobile,"When does my reservation expire?","which reservation");
  await ask(mobile,"What happens if my extension overlaps someone else's booking?","original reservation stays active");
  console.log("PASS: reloaded cap and seat count, explicit raise, seat limit clarification, quote and reservation scope, cited extension conflict.");
  console.log("PASS: desktop and mobile free-text discovery, body edit, comparison, selected reference, cited pickup, unsupported question, exact quote, competing approvals, extension, reload, clear-chat retention, cancellation and impossible budget.");
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
