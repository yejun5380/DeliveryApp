const assert=require('node:assert/strict');
const {buildPath,position,state}=require('../static/delivery.js');
const points=[{lat:0,lng:0},{lat:0,lng:1},{lat:0,lng:4}];
const path=buildPath(points);
assert.ok(Math.abs(position(path,.5).lng-2)<1e-9); // unequal segment lengths
assert.deepEqual(position(path,0),points[0]);
assert.deepEqual(position(path,1),points[2]);
assert.deepEqual(position(buildPath([points[0],points[0],points[1]]),0),points[0]);
const snapshot={preparation:600,duration:120,scale:10};
for (const [seconds,stage] of [[0,0],[20,1],[40,2],[60,3],[72,4]]) assert.equal(state(seconds,snapshot).stage,stage);
assert.equal(state(66,snapshot).rider,.5);
assert.equal(state(7200,snapshot).progress,1);
assert.equal(state(-5,snapshot).rider,0);
console.log('PASS: distance interpolation, duplicate points, endpoints, five stages, shared clock and refresh reconstruction');
