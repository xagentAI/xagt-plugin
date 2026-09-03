"use strict";

function canonicalJson(value){
  if(value===null)return "null";
  if(Array.isArray(value)){
    return "["+value.map(canonicalJson).join(",")+"]";
  }
  if(typeof value==="object"){
    const keys=Object.keys(value).sort();
    return "{"+keys.map(k=>JSON.stringify(k)+":"+canonicalJson(value[k])).join(",")+"}";
  }
  return JSON.stringify(value);
}

module.exports={canonicalJson};
