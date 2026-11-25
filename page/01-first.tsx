import{Page,Section,Text,Callout,Select,Input,Button,Toggle,Table,Rows,Properties,Status,Segmented,Floating,BackToTop,TextLink,useState,useMemo,useEffect,useGrokTheme,} from"grok/canvas";import type{CSSProperties} from"grok/canvas";type Step="signin"|"archive"|"pick"|"review"|"run";type HomePhase="choose"|"grabbing"|"waiting"|"ready"|"manual";type RunPhase="idle"|"running"|"done";/*@B*/
//^@@0@@
/*@@B*//*@A*/
//~@@1@@
/*@@A*/type PostType="post"|"reply"|"repost"|"quote";type TimeMode="none"|"all"|"older"|"years";type MediaKind="photo"|"video"|"animated_gif";/*@A*/
//~@@2@@
/*@@A*/type PageTone="info"|"warn"|"error"|"ok";type PageStatus={tone:PageTone;lead:string;text:string};const START_STEP:Step="signin";const START_PHASE:HomePhase="choose";const START_RUN:RunPhase="idle";const SIGNED_IN_HANDLE:string="";/*@A*/
//~@@3@@
/*@@A*//*@B*/
//^@@4@@
/*@@B*/const PAGE_STATUS:PageStatus|null=null;/*@A*/
//~@@5@@
/*@@A*/type Post={id:string;daysAgo:number;type:PostType;likes:number;replies:number;text:string;summary:string;media:boolean;gif?:boolean;mediaKind?:MediaKind;replyTo?:string;inReplyToId?:string;mentions?:boolean;extraMentions?:boolean;thread?:string;profilePin?:boolean;community?:boolean;repostOf?:string;quoteOf?:string;selfReply?:boolean;};type Rules={timeMode:TimeMode;olderDays:number;yearFrom:number;yearTo:number;protectDays:number;posts:boolean;replies:boolean;reposts:boolean;quotes:boolean;community:boolean;mediaPhotos:boolean;mediaVideos:boolean;mediaGifs:boolean;mediaText:boolean;postsLikesMax:number;repliesLikesMax:number;repliesMax:number;deleteWords:string[];keepWords:string[];replyHandles:string[];olderDate:string;protectDate:string;repostOf:string;topic:string;skipMentions:boolean;keepThreads:boolean;keepProfilePin:boolean;keepMedia:boolean;selfReplies:boolean;deleteSlurs:boolean;};/*@A*/
//~@@6@@
/*@@A*//*@B*/
//^@@7@@
/*@@B*//*@A*/
//~@@8@@
/*@@A*/ /*@A*/
//~@@9@@
/*@@A*/ /*@A*/
//~@@10@@
/*@@A*/ /*@A*/
//~@@11@@
/*@@A*/ /*@A*/
//~@@12@@
/*@@A*/ /*@A*/
//~@@13@@
/*@@A*/ /*@A*/
//~@@14@@
/*@@A*/ /*@A*/
//~@@15@@
/*@@A*/ /*@A*/
//~@@16@@
/*@@A*/ /*@A*/
//~@@17@@
/*@@A*/ /*@A*/
//~@@18@@
/*@@A*/ /*@A*/
//~@@19@@
/*@@A*/ /*@A*/
//~@@20@@
/*@@A*/ /*@A*/
//~@@21@@
/*@@A*/ /*@B*/
//^@@22@@
/*@@B*/ /*@A*/
//~@@23@@
/*@@A*/ /*@B*/
//^@@24@@
/*@@B*/ /*@A*/
//~@@25@@
/*@@A*/ /*@A*/
//~@@26@@
/*@@A*/ /*@A*/
//~@@27@@
/*@@A*/ /*@A*/
//~@@28@@
/*@@A*/ /*@A*/
//~@@29@@
/*@@A*/ /*@A*/
//~@@30@@
/*@@A*/ /*@A*/
//~@@31@@
/*@@A*/ /*@A*/
//~@@32@@
/*@@A*/ /*@A*/
//~@@33@@
/*@@A*/ /*@A*/
//~@@34@@
/*@@A*/ /*@A*/
//~@@35@@
/*@@A*/ /*@A*/
//~@@36@@
/*@@A*/ /*@A*/
//~@@37@@
/*@@A*/ /*@B*/
//^@@38@@
/*@@B*/ /*@B*/
//^@@39@@
/*@@B*/ /*@B*/
//^@@40@@
/*@@B*/ const POOL:Post[]=[];const LOADED_RULES:Rules|null=null;/*@A*/
//~@@41@@
/*@@A*//*@B*/
//^@@42@@
/*@@B*/const LOADED_FAILED:Array<{id:string;reason:string}>=[];/*@B*/
//^@@43@@
/*@@B*/type LoadedTotals={scanned:number;matched:number;kept:number;noDate:number;fastCount:number;byType:Array<[string,string,string]>};const LOADED_TOTALS:LoadedTotals|null=null;/*@B*/
//^@@44@@
/*@@B*/const BASE:Rules={timeMode:"none",olderDays:365,olderDate:"",yearFrom:0,yearTo:0,protectDays:0,protectDate:"",posts:false,replies:false,reposts:false,quotes:false,community:false,mediaPhotos:false,mediaVideos:false,mediaGifs:false,mediaText:false,postsLikesMax:-1,repliesLikesMax:-1,repliesMax:-1,deleteWords:[],keepWords:[],replyHandles:[],repostOf:"",topic:"",skipMentions:false,keepThreads:false,keepProfilePin:true,keepMedia:false,selfReplies:false,deleteSlurs:false,};/*@A*/
//~@@45@@
/*@@A*/ /*@A*/
//~@@46@@
/*@@A*/ /*@A*/
//~@@47@@
/*@@A*/ /*@B*/
//^@@48@@
/*@@B*/ /*@A*/
//~@@49@@
/*@@A*/ /*@A*/
//~@@50@@
/*@@A*/ /*@A*/
//~@@51@@
/*@@A*/ /*@A*/
//~@@52@@
/*@@A*/ /*@A*/
//~@@53@@
/*@@A*/ /*@A*/
//~@@54@@
/*@@A*/ const STEP_META:Record<Step,{n:number;label:string;heading:string;hint:string}>={signin:{n:1,label:"Sign in",heading:"Sign in to X",hint:"You sign in once, yourself, in the bot's own browser. The bot never sees your password."},archive:{n:2,label:"Archive",heading:"Get your archive",hint:"X emails the file in about 1–3 days, and the bot loads it for you."},pick:{n:3,label:"Pick",heading:"Pick what goes",hint:"Start with a quick cleanup or set your own rules."},review:{n:4,label:"Review",heading:"Review your cleanup",hint:"Check the totals, pick Free or Fast, download the list, then approve once."},run:{n:5,label:"Run",heading:"Running",hint:"It runs on its own at X's pace. You can close this."},};/*@A*/
//~@@55@@
/*@@A*/ /*@A*/
//~@@56@@
/*@@A*/ /*@A*/
//~@@57@@
/*@@A*/ /*@A*/
//~@@58@@
/*@@A*/ export default function App(){const theme=useGrokTheme();const _s0:CSSProperties={fontSize:14,color:theme.text.secondary,lineHeight:1.5};/*@A*/
//~@@59@@
/*@@A*//*@B*/
//^@@60@@
/*@@B*//*@A*/
//~@@61@@
/*@@A*//*@B*/
//^@@62@@
/*@@B*//*@A*/
//~@@63@@
/*@@A*/const _s8:CSSProperties={display:"flex",flexDirection:"column",gap:8};/*@A*/
//~@@64@@
/*@@A*//*@B*/
//^@@65@@
/*@@B*/const _s12:CSSProperties={minWidth:0};const pool=POOL;const[step,setStep]=useState<Step>(START_STEP);const[phase,setPhase]=useState<HomePhase>(START_PHASE);const[runPhase,setRunPhase]=useState<RunPhase>(START_RUN);const[rules,setRules]=useState<Rules>(LOADED_RULES||BASE);/*@A*/
//~@@66@@
/*@@A*//*@B*/
//^@@67@@
/*@@B*//*@A*/
//~@@68@@
/*@@A*//*@B*/
//^@@69@@
/*@@B*//*@A*/
//~@@70@@
/*@@A*//*@B*/
//^@@71@@
/*@@B*//*@A*/
//~@@72@@
/*@@A*/const[likesLast,setLikesLast]=useState({posts:5,replies:5});/*@B*/
//^@@73@@
/*@@B*/const[recentOnly,setRecentOnly]=useState(false);/*@B*/
//^@@74@@
/*@@B*/const[narrow,setNarrow]=useState(false);const[barHidden,setBarHidden]=useState(false);/*@A*/
//~@@75@@
/*@@A*/useEffect(()=>{if(!narrow||step==="review"){setBarHidden(false);return;} let lastY=window.scrollY;let stopTimer:ReturnType<typeof window.setTimeout>|undefined;const onScroll=()=>{const y=window.scrollY;if(y>lastY+2&&y>24)setBarHidden(true);else if(y<lastY-2)setBarHidden(false);lastY=y;if(stopTimer!==undefined)window.clearTimeout(stopTimer);stopTimer=window.setTimeout(()=>setBarHidden(false),450);};window.addEventListener("scroll",onScroll,{passive:true});return()=>{window.removeEventListener("scroll",onScroll);if(stopTimer!==undefined)window.clearTimeout(stopTimer);};},[narrow,step]);/*@A*/
//~@@76@@
/*@@A*/useEffect(()=>{setLikesLast((prev)=>({posts:rules.postsLikesMax>=0?rules.postsLikesMax:prev.posts,replies:rules.repliesLikesMax>=0?rules.repliesLikesMax:prev.replies,}));},[rules.postsLikesMax,rules.repliesLikesMax]);/*@A*/
//~@@77@@
/*@@A*//*@B*/
//^@@78@@
/*@@B*/const scanned=LOADED_TOTALS?LOADED_TOTALS.scanned:pool.length;/*@A*/
//~@@79@@
/*@@A*//*@B*/
//^@@80@@
/*@@B*/const failedCount=LOADED_FAILED.length;/*@B*/
//^@@81@@
/*@@B*//*@A*/
//~@@82@@
/*@@A*//*@B*/
//^@@83@@
/*@@B*//*@A*/
//~@@84@@
/*@@A*/const scrollToId=(id:string)=>{const el=document.getElementById(id);if(el)el.scrollIntoView({behavior:"smooth",block:"start"});};/*@A*/
//~@@85@@
/*@@A*/const goStep=(id:Step)=>{setStep(id);};/*@A*/
//~@@86@@
/*@@A*//*@B*/
//^@@87@@
/*@@B*/const primary=(():{label:string;action:()=>void;disabled?:boolean}|null=>{if(step==="signin")return null;if(step==="archive")return null;/*@A*/
//~@@88@@
/*@@A*/ if(step==="pick")return{label:"Next: review my list →",action:()=>goStep("review"),disabled:true/*@B*/
//^@@89@@
/*@@B*/};if(step==="review")return null;if(failedCount>0)return{label:"Open failure tray",action:()=>scrollToId("run-tray")};return null;})();const heading=step==="run"&&runPhase==="done"?"Done":STEP_META[step].heading;const hint=step==="run"&&runPhase==="done"?"Here is what was verified, plus optional cleanup on Google and Wayback.":STEP_META[step].hint;/*@A*/
//~@@90@@
/*@@A*/const panel:CSSProperties={borderRadius:16,border:`1px solid ${theme.border.default}`,background:theme.bg.subtle,padding:24,};/*@A*/
//~@@91@@
/*@@A*/const tapLine=(sentence:string)=>(<div style={{fontSize:14,color:theme.text.secondary,lineHeight:1.5,marginTop:10}}>{sentence}</div>);const xDownloadLink=(<div style={{fontSize:13,color:theme.text.secondary,marginTop:10,lineHeight:1.45}}>Or request it yourself on <TextLink href="https://x.com/settings/download_your_data">X's Download your data page</TextLink> (opens in your own browser).</div>);const recentOnlyOffer=(<div style={_s8}><div style={_s0}>Optional, while you wait for the archive: start with your recent posts only (about the last 3,200). This is not your full history, and it still needs a preview and one Approve.</div><div>{tapLine("Start with recent posts only with the tap card in the chat.")}</div></div>);/*@A*/
//~@@92@@
/*@@A*//*@B*/
//^@@93@@
/*@@B*//*@A*/
//~@@94@@
/*@@A*//*@B*/
//^@@95@@
/*@@B*/return(<Page title="X Post Cleaner" width="full" summary="Free. No card. Nothing to cancel. Sign in, get your archive, pick what goes, approve once." palette={["#6EC1FF","#4AA3E0","#B8DFFF"]}><style>{`.xpc-wrap{max-width: 1440px;margin: 0 auto;padding: 4px 12px 96px;box-sizing: border-box}.xpc-stepper{display: flex;align-items: center;gap: 6px;margin: 0 0 20px}.xpc-step{display: flex;align-items: center;gap: 8px;min-width: 0;background: none;border: 0;padding: 6px 4px;cursor: pointer;text-align: left;font: inherit;color: inherit}.xpc-step[disabled]{cursor: default;opacity: 0.45}.xpc-num{width: 26px;height: 26px;border-radius: 999px;display: inline-flex;align-items: center;justify-content: center;font-size: 13px;font-weight: 600;flex-shrink: 0}.xpc-step-label{font-size: 14px;font-weight: 600;white-space: nowrap}.xpc-shell{display: grid;grid-template-columns: 200px minmax(0, 1fr) 280px;gap: 32px;align-items: start}.xpc-rail, .xpc-summary{position: sticky;top: 24px}h1{color: #8BE9FF !important;text-shadow: 0 0 6px rgba(110, 193, 255, 0.95), 0 0 18px rgba(74, 163, 224, 0.55), 0 0 36px rgba(110, 193, 255, 0.35)}@media (max-width: 1100px){.xpc-shell{grid-template-columns: minmax(0, 1fr)}.xpc-rail, .xpc-summary{display: none}}@media (max-width: 760px){.xpc-step-label{font-size: 12px}.xpc-wrap{padding: 0 0 112px}}`}</style><div className={narrow&&primary&&step!=="review"?"xpc-wrap xpc-wrap-pickbar":"xpc-wrap"} style={{fontFamily:theme.font.family,color:theme.text.primary}}>{SIGNED_IN_HANDLE!==""&&(<div style={{fontSize:13,color:theme.text.secondary,margin:"0 0 8px",lineHeight:1.45}}>{`Signed in as @${SIGNED_IN_HANDLE.replace(/^@/,"")}`}</div>)}<div className="xpc-stepper" role="navigation" aria-label="Cleanup steps">{(["signin","archive","pick","review","run"]as Step[]).map((id,i)=>{const meta=STEP_META[id];const active=step===id;const locked=(id==="run"||id==="review")/*@B*/
//^@@96@@
/*@@B*/;const label=id==="run"&&runPhase==="done"?"Done":meta.label;return(<div key={id} style={{display:"flex",alignItems:"center",gap:6,flex:i<4?1:"0 0 auto",minWidth:0}}><button type="button" className="xpc-step" disabled={locked||id==="pick"/*@A*/
//~@@97@@
/*@@A*/} onClick={()=>goStep(id)} aria-current={active?"step":undefined}><span className="xpc-num" style={{background:active?theme.fill.primary:theme.fill.secondary,color:active?theme.text.onPrimary:theme.text.secondary}}>{meta.n}</span><span className="xpc-step-label" style={{color:active?theme.text.primary:theme.text.secondary}}>{label}</span></button>{i<4&&<div style={{flex:1,height:1,background:theme.border.default,minWidth:12}}/>}</div>);})}</div>{PAGE_STATUS&&(PAGE_STATUS.lead!==""||PAGE_STATUS.text!=="")&&(<div role="status" style={{margin:"0 0 20px",padding:"12px 14px",borderRadius:12,border:`1px solid ${theme.border.default}`,background:PAGE_STATUS.tone==="ok"?theme.fill.successSubtle:PAGE_STATUS.tone==="info"?theme.fill.accentSubtle:theme.bg.subtle}}>{PAGE_STATUS.lead!==""&&(<div style={{fontSize:14,fontWeight:650,color:PAGE_STATUS.tone==="ok"?theme.text.success:PAGE_STATUS.tone==="info"?theme.text.accent:theme.text.warning}}>{PAGE_STATUS.lead}</div>)}{PAGE_STATUS.text!==""&&(<div style={{fontSize:14,color:theme.text.secondary,lineHeight:1.45,marginTop:PAGE_STATUS.lead!==""?4:0}}>{PAGE_STATUS.text}</div>)}</div>)}<div className="xpc-shell">{null/*@A*/
//~@@98@@
/*@@Ac*/}<main style={_s12}><div style={{marginBottom:22}}><h2 style={{margin:0,fontSize:theme.font.heading2.fontSize,lineHeight:theme.font.heading2.lineHeight,fontFamily:theme.font.family,color:theme.text.primary,fontWeight:650}}>{heading}</h2><p style={{margin:"6px 0 0",fontSize:15,lineHeight:1.5,color:theme.text.secondary}}>{hint}</p>{null/*@B*/
//^@@99@@
/*@@Bc*/}</div>{step==="signin"&&(<div style={{display:"flex",flexDirection:"column",gap:20}}><div style={_s0}>Sign in in the X window in the chat. If you already signed in, you're set.</div>{null/*@A*/
//~@@100@@
/*@@Ac*/}</div>)}{step==="archive"&&(<div style={{display:"flex",flexDirection:"column",gap:20}}><div id="arc-get" style={{display:"flex",flexDirection:"column",gap:16}}>{phase==="choose"&&(<><div style={{...panel,background:theme.fill.accentSubtle,padding:"28px 28px"}}><Rows rows={[{title:"1. Request",detail:"The bot taps Download your data on X, in its own signed-in browser."},{title:"2. Wait",detail:"X emails a link, usually in 1–3 days. While you wait, choose what to delete: old posts, replies with few likes, reposts, and more."},{title:"3. Load",detail:"The bot downloads the file and loads it here. You never handle the ZIP."},]}/><div style={{marginTop:18}}>{xDownloadLink}</div></div>{tapLine("Tap Drop your archive in chat if you already have the file.")}{recentOnlyOffer}</>)}{(phase==="grabbing"||phase==="waiting")&&(<div style={_s0}>Your archive has been requested. X usually takes 1 to 3 days. The bot will pull it in automatically and let you know when it's ready. Meanwhile, set up your rules.</div>)}{phase==="manual"&&(<>{tapLine("Tap Drop your archive in chat. The bot reads the ZIP on its computer.")}<div><Button label="Let the bot fetch it instead" variant="quiet" onClick={()=>setPhase("choose")}/></div></>)}{phase==="ready"&&(<>{recentOnly?(<Callout tone="info" lead="Recent only · not your full history">Your recent posts (about the last 3,200 X can show). Older posts are not in this list. Your official archive is still the way to clean your full history.</Callout>):(<Callout tone="success" lead="Archive loaded">{`${scanned.toLocaleString("en-US")} posts found. Next, choose what goes.`}</Callout>)}{recentOnly&&(<div>{tapLine("Wait for the full archive with the tap card in the chat.")}</div>)}</>)}</div>{null/*@A*/
//~@@101@@
/*@@Ac*/}</div>)}{null/*@A*/
//~@@102@@
/*@@Ac*/}{null/*@B*/
//^@@103@@
/*@@Bc*/}{null/*@B*/
//^@@104@@
/*@@Bc*/}</main>{null/*@B*/
//^@@105@@
/*@@Bc*/}</div></div>{null/*@B*/
//^@@106@@
/*@@Bc*/}</Page>);}