import { chromium } from 'playwright';
import fs from 'node:fs';
import assert from 'node:assert/strict';
const out = 'outputs/company-governance-qa';
fs.mkdirSync(out,{recursive:true});
const browser = await chromium.launch({headless:true});
try {
  for (const width of [1440,390]) {
    const page = await browser.newPage({viewport:{width,height:1000}});
    const errors=[]; page.on('pageerror', e=>errors.push(e.message));
    await page.route('**/api/v1/**', async route=>{
      const url=new URL(route.request().url());
      const send=body=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
      if(url.pathname==='/api/v1/auth/me')return send({user_id:'00000000-0000-0000-0000-000000000099',name:'治理验收用户',status:'active',company_roles:['boss'],active_company_role:'boss',is_business_user:true,can_discover_l5:true,project_memberships:[]});
      if(url.pathname==='/api/v1/company-governance')return send({items:['中华人民共和国公司法2018年10月修正版','同博科技企业文化落地方案（讨论稿）','资产证券化市场月报：消费贷ABS的那些事儿','岗位胜任能力模型考核','企业运营管理体系建设'].map((title,i)=>({asset_id:'fixture-'+i,title,asset_status:url.searchParams.get('view')==='archived'?'archived':'active',confidentiality_level:'L2',summary:'用于验收的安全摘要：该资料属于历史研究或工作过程材料，需核验适用时间与正式版本。',updated_at:'2026-09-22T00:00:00Z',archived_at:'2026-09-22T00:00:00Z',archive_reason:'历史参考',signals:[['policy_age','draft','research_age','content_check','same_title'][i]]})),total:5,page:1,page_size:25,counts:{all:2724,candidates:480,archived:13}});
      if(url.pathname.endsWith('/events'))return send({items:[]});
      return send({items:[],total:0,unread_count:0});
    });
    await page.goto('http://127.0.0.1:5187/company-governance');
    await page.getByRole('heading',{name:'公司库治理',exact:true}).waitFor();
    await page.getByRole('button',{name:'中华人民共和国公司法2018年10月修正版',exact:true}).waitFor();
    await page.screenshot({path:`${out}/${width}.png`,fullPage:true});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'page overflow');
    await page.getByRole('button',{name:'中华人民共和国公司法2018年10月修正版',exact:true}).click();
    await page.getByRole('heading',{name:'安全摘要',exact:true}).waitFor();
    await page.screenshot({path:`${out}/${width}-detail.png`,fullPage:true});
    await page.getByRole('button',{name:'关闭详情'}).click();
    await page.getByLabel('选择本页全部资料').check();
    await page.getByRole('button',{name:'预览归档'}).click();
    await page.getByRole('dialog').waitFor();
    assert(await page.getByRole('button',{name:'确认归档',exact:true}).isDisabled());
    await page.screenshot({path:`${out}/${width}-confirm.png`,fullPage:true});
    assert.deepEqual(errors,[]);
    await page.close();
  }
  console.log('Desktop/mobile layout, drawer, batch preview and required reason passed.');
} finally {await browser.close();}
