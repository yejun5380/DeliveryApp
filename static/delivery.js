/* Pure calculations are shared by the browser and Node tests. */
(function (root) {
    function distance(a, b) {
        const rad = Math.PI / 180;
        const v = Math.sin((b.lat-a.lat)*rad/2)**2 + Math.cos(a.lat*rad)*Math.cos(b.lat*rad)*Math.sin((b.lng-a.lng)*rad/2)**2;
        return 6371000 * 2 * Math.asin(Math.sqrt(Math.min(1, v)));
    }
    function buildPath(points) {
        const cumulative = [0];
        for (let i=1; i<points.length; i++) cumulative.push(cumulative[i-1]+distance(points[i-1],points[i]));
        return {points, cumulative, length:cumulative[cumulative.length-1]};
    }
    function position(path, progress) {
        const {points, cumulative, length} = path;
        if (progress <= 0 || !length) return points[0];
        if (progress >= 1) return points[points.length-1];
        const target = length*progress;
        let low=1, high=points.length-1;
        while(low<high) { const mid=(low+high)>>1; if(cumulative[mid]<target) low=mid+1; else high=mid; }
        const a=points[low-1], b=points[low];
        const fraction=(target-cumulative[low-1])/(cumulative[low]-cumulative[low-1] || 1);
        return {lat:a.lat+(b.lat-a.lat)*fraction,lng:a.lng+(b.lng-a.lng)*fraction};
    }
    function state(elapsed, snapshot) {
        const virtual=Math.max(0,elapsed)*snapshot.scale;
        const prep=snapshot.preparation, total=prep+snapshot.duration;
        return {stage:virtual>=total?4:virtual>=prep?3:virtual>=prep*2/3?2:virtual>=prep/3?1:0,
            progress:Math.min(1,virtual/total), rider:Math.max(0,Math.min(1,(virtual-prep)/snapshot.duration))};
    }
    const api={buildPath,position,state};
    if(typeof module!=='undefined') module.exports=api;
    root.DeliverySimulation=api;
})(globalThis);
if(typeof document!=='undefined') {
    const {snapshot,elapsed}=JSON.parse(document.getElementById('delivery-data').textContent);
    if(snapshot) {
        const started=performance.getEntriesByType('navigation')[0]?.responseStart || performance.now(), path=DeliverySimulation.buildPath(snapshot.path);
        let marker=null, map=null, timer=null;
        if(globalThis.kakao?.maps) {
            const points=snapshot.path.map(p=>new kakao.maps.LatLng(p.lat,p.lng));
            map=new kakao.maps.Map(document.getElementById('map'),{center:points[0],level:4});
            new kakao.maps.Polyline({map,path:points,strokeWeight:5,strokeColor:'#3366ff'});
            const bounds=new kakao.maps.LatLngBounds(); points.forEach(p=>bounds.extend(p)); map.setBounds(bounds);
            const icon=document.createElement('div'); icon.textContent='🛵'; icon.style.fontSize='30px';
            marker=new kakao.maps.CustomOverlay({position:points[0],content:icon,yAnchor:1,zIndex:10});
            new kakao.maps.Marker({map,position:points[0],title:snapshot.representative});
            new kakao.maps.Marker({map,position:points[points.length-1],title:'배달 목적지'});
        } else document.getElementById('map').textContent='지도를 불러오지 못했습니다. JavaScript 키·허용 도메인·네트워크를 확인해 주세요.';
        const labels=['주문 접수','음식 준비 중','배달기사 배정','배달 중','가상 배달 완료'];
        function stop() {if(timer!==null) clearInterval(timer); timer=null;}
        function update() {
            const current=DeliverySimulation.state(elapsed+(performance.now()-started)/1000,snapshot);
            document.getElementById('delivery-status').textContent=labels[current.stage];
            document.getElementById('progress').value=current.progress;
            document.getElementById('delivery-message').textContent=`배달 진행률 ${(current.progress*100).toFixed(1)}%`;
            if(marker) {const p=DeliverySimulation.position(path,current.rider); marker.setPosition(new kakao.maps.LatLng(p.lat,p.lng)); marker.setMap(current.stage>=2?map:null);}
            if(current.stage===4) stop();
            return current.stage;
        }
        function start() {stop(); if(update()!==4 && !document.hidden) timer=setInterval(update,100);}
        document.addEventListener('visibilitychange',()=>document.hidden?stop():start());
        window.addEventListener('pagehide',stop);
        window.addEventListener('pageshow',start);
        start();
    }
}
