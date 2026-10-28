/** One catalog for appearance selection and safe saved-theme restoration. */
export const THEMES = Object.freeze([
  {id:'moonlit', label:'Moonlight', icon:'moon', color:'#091524', artwork:'/ui/moonlit/moon-lake-square.png'},
  {id:'forest', label:'Forest', icon:'leaf', color:'#071513', artwork:null},
  {id:'deck', label:'Sleep Deck', icon:'layers', color:'#151419', artwork:null},
  {id:'cloudstorm', label:'Cloudstorm', icon:'cloud', color:'#09111d', artwork:'/ui/cloudstorm/cloudstorm-original.jpg'},
]);
export const resolveTheme = id => THEMES.find(theme => theme.id === id) || THEMES[0];
export const nativeOwnsInsets = userAgent => /\bSleepSoundsAndroid\//.test(userAgent || '');
