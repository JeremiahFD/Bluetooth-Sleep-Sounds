import {IMAGE_EXTENSIONS} from './mediaSelection.js';
export const stem=name=>name.replace(/\.[^.]+$/,'').toLowerCase().replace(/[\s_-]+/g,'');
export function mergeQueue(stage, chosen, formats){
 const jobs=stage.jobs.map(j=>({...j})),images=[...stage.images];
 let seq=stage.seq||0;
 for(const file of Array.from(chosen||[])){
  if(!file.size)throw new Error('Empty file '+file.name);
  const ext='.'+(file.name.split('.').pop()||'').toLowerCase();
  if(formats.includes(ext))jobs.push({id:'a'+(++seq),file,imageId:null,uploadedId:null,status:'queued',error:''});
  else if(IMAGE_EXTENSIONS.includes(ext)){
   if(file.size>8*1024*1024)throw new Error('Image must be under 8 MB: '+file.name);
   images.push({id:'i'+(++seq),file});
  }else throw new Error('Unsupported file: '+file.name);
 }
 const used=new Set(jobs.map(j=>j.imageId).filter(Boolean));
 for(const job of jobs){
  if(job.imageId||job.status==='done')continue;
  const imagesMatching=images.filter(i=>!used.has(i.id)&&stem(i.file.name)===stem(job.file.name));
  const jobsMatching=jobs.filter(j=>!j.imageId&&j.status!=='done'&&stem(j.file.name)===stem(job.file.name));
  if(imagesMatching.length===1&&jobsMatching.length===1){job.imageId=imagesMatching[0].id;used.add(job.imageId);}
 }
 const unassignedJobs=jobs.filter(j=>!j.imageId&&j.status!=='done');
 const unusedImages=images.filter(i=>!used.has(i.id));
 if(unassignedJobs.length===1&&unusedImages.length===1)unassignedJobs[0].imageId=unusedImages[0].id;
 return {jobs,images,seq};
}
export function assignQueueImage(stage,jobId,imageId){
 if(imageId&&!stage.images.some(i=>i.id===imageId))throw new Error('Unknown image');
 if(imageId&&stage.jobs.some(j=>j.id!==jobId&&j.imageId===imageId))throw new Error('Image already assigned');
 return {...stage,jobs:stage.jobs.map(j=>j.id===jobId?{...j,imageId:imageId||null}:j)};
}
