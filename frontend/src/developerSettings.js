export const GAIN_METER_KEY='sleep-developer-gain-meter';

export function readGainMeterEnabled(storage){
 try{return (storage??globalThis.localStorage)?.getItem(GAIN_METER_KEY)==='true'}catch{return false}
}

export function saveGainMeterEnabled(value,storage){
 try{(storage??globalThis.localStorage)?.setItem(GAIN_METER_KEY,String(value))}catch{}
 return value===true;
}
