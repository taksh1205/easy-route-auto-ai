const{chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{}),headless:true,args:['--no-sandbox']});const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto('http://localhost:3000');await page.getByRole('heading',{name:'2021 Toyota Corolla'}).waitFor();
  await page.evaluate(()=>sessionStorage.setItem('easy-session','{malformed'));await page.reload();
  await page.getByLabel('What are you looking for?').fill('SUV under $20,000');await page.getByRole('button',{name:'Search with assistant'}).click();await page.getByText('Available matches are listed below.').waitFor();
  if(await page.getByRole('heading',{name:'2021 Toyota Corolla'}).count())throw Error('Hard filters failed');
  await page.getByRole('button',{name:'View appointment times'}).first().click();await page.getByRole('button',{name:'Prepare booking proposal'}).click();
  await page.getByRole('button',{name:'Confirm exact booking'}).click();await page.getByText(/CONFIRMED booking · committed record/).waitFor();
  await page.reload();await page.getByRole('button',{name:'Prepare cancellation'}).waitFor();
  await page.getByLabel('What are you looking for?').fill('What is the warranty policy?');await page.getByRole('button',{name:'Search with assistant'}).click();await page.getByText(/Synthetic policy excerpt · warranties/).waitFor();
  await page.getByRole('button',{name:'Clear chat and personal lead data'}).click();await page.getByRole('button',{name:'Prepare cancellation'}).waitFor();await page.getByRole('heading',{name:'2021 Toyota Corolla'}).waitFor();
  await page.getByRole('button',{name:'Prepare cancellation'}).click();await page.getByRole('button',{name:'Confirm exact cancellation'}).click();await page.getByText(/CONFIRMED cancellation · committed record/).waitFor();
  await page.getByRole('textbox',{name:'Name',exact:true}).fill('Synthetic Browser Test');await page.getByRole('textbox',{name:'Email',exact:true}).fill('browser@example.com');await page.getByRole('checkbox',{name:/I consent/}).check();await page.getByRole('button',{name:'Prepare lead proposal'}).click();await page.getByRole('button',{name:'Confirm exact lead'}).click();await page.getByText(/CONFIRMED lead · committed record/).waitFor();
  if(errors.length)throw Error(errors.join('; '));console.log('PASS: malformed storage recovery → SQL filters → exact booking proposal → confirmation → reload → actual neural citations → clear chat preserves appointment → cancellation → lead confirmation; no page errors');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
