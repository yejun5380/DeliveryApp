const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element {
    constructor(){this.events={};this.dataset={};this.disabled=true;this.open=false;this.textContent='';}
    addEventListener(name,fn){(this.events[name]||=[]).push(fn);}
    fire(name,event={}){for(const fn of this.events[name]||[])fn(event);}
    querySelector(){return this.button;}
    showModal(){this.open=true;}
    close(){this.open=false;}
    requestSubmit(){let prevented=false;this.fire('submit',{preventDefault(){prevented=true;}});if(!prevented)this.submissions=(this.submissions||0)+1;}
}
const enough=new Element(),short=new Element();
enough.dataset={canPurchase:'true',name:'어른폰 18',price:'1,990,000'};
short.dataset={canPurchase:'false',name:'부족한 상품',price:'1,990,000'};
enough.button=new Element();short.button=new Element();
const ids=Object.fromEntries(['shop-confirm','shop-confirm-name','shop-confirm-price','shop-confirm-cancel','shop-confirm-buy'].map(id=>[id,new Element()]));
const win=new Element();
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/shop.js'),'utf8'),{
    document:{querySelectorAll:()=>[enough,short],getElementById:id=>ids[id]},window:win,
});
assert.equal(enough.button.disabled,false);assert.equal(short.button.disabled,true);
enough.requestSubmit();assert.equal(ids['shop-confirm'].open,true);assert.equal(enough.submissions,undefined);
assert.equal(ids['shop-confirm-name'].textContent,'어른폰 18');assert.equal(ids['shop-confirm-price'].textContent,'1,990,000');
ids['shop-confirm-cancel'].fire('click');assert.equal(ids['shop-confirm'].open,false);assert.equal(enough.submissions,undefined);
short.requestSubmit();assert.equal(short.submissions,undefined);assert.equal(ids['shop-confirm'].open,false);
enough.requestSubmit();ids['shop-confirm-buy'].fire('click');
assert.equal(enough.submissions,1);assert.equal(enough.button.disabled,true);assert.equal(ids['shop-confirm'].open,false);
enough.requestSubmit();ids['shop-confirm-buy'].fire('click');assert.equal(enough.submissions,1,'double click cannot submit twice');
win.fire('pageshow');assert.equal(enough.button.disabled,false);assert.equal(short.button.disabled,true);
enough.requestSubmit();ids['shop-confirm'].fire('cancel');ids['shop-confirm'].close();ids['shop-confirm-buy'].fire('click');assert.equal(enough.submissions,1);
console.log('PASS: point shop confirmation, cancel/Escape, insufficient funds, duplicate submission and back navigation');
