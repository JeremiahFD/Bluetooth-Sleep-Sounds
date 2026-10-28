import React from 'react';
import './cloudstorm-controls.css';
/** Experimental artwork skin: HTML retains semantics, labels and all interactions. */
export function CloudstormButton({variant='secondary',className='',children,...props}){
 return <button type="button" {...props} className={'cloudstorm-button cloudstorm-button--'+variant+' '+className}><span>{children}</span></button>;
}
