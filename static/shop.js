(() => {
    const forms=[...document.querySelectorAll('.shop-purchase-form')];
    const dialog=document.getElementById('shop-confirm');
    if(!dialog) return;
    let pending=null, approved=null, busy=false;
    function reset() {
        busy=false;pending=null;approved=null;
        if(dialog.open) dialog.close();
        forms.forEach(form=>{
            const button=form.querySelector('button');
            button.disabled=form.dataset.canPurchase!=='true';
            button.textContent=button.disabled?'포인트 부족':'가상 구매하기';
        });
    }
    forms.forEach(form=>form.addEventListener('submit',event=>{
        if(busy || form.dataset.canPurchase!=='true') {event.preventDefault();return;}
        if(approved===form) {
            busy=true;approved=null;
            forms.forEach(item=>{item.querySelector('button').disabled=true;});
            form.querySelector('button').textContent='구매 처리 중...';
            return;
        }
        event.preventDefault();pending=form;
        document.getElementById('shop-confirm-name').textContent=form.dataset.name;
        document.getElementById('shop-confirm-price').textContent=form.dataset.price;
        dialog.showModal();
    }));
    document.getElementById('shop-confirm-cancel').addEventListener('click',()=>{pending=null;dialog.close();});
    dialog.addEventListener('cancel',()=>{pending=null;});
    document.getElementById('shop-confirm-buy').addEventListener('click',()=>{
        if(!pending || busy) return;
        const form=pending;pending=null;approved=form;dialog.close();form.requestSubmit();
    });
    window.addEventListener('pageshow',reset);
    reset();
})();
