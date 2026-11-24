import{Page,Section,Text,Callout,Select,Input,Button,Toggle,Table,Rows,Properties,BulletList,Status,Segmented,Floating,BackToTop,TextLink,useState,useMemo,useEffect,useGrokTheme,} from"grok/canvas";import type{CSSProperties} from"grok/canvas";type Step="signin"|"archive"|"pick"|"review"|"run";type HomePhase="choose"|"grabbing"|"waiting"|"ready"|"manual";type RunPhase="idle"|"running"|"done";/*@B*/
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
/*@@A*/type Post={id:string;daysAgo:number;type:PostType;likes:number;replies:number;text:string;summary:string;media:boolean;gif?:boolean;mediaKind?:MediaKind;replyTo?:string;inReplyToId?:string;mentions?:boolean;extraMentions?:boolean;thread?:string;profilePin?:boolean;community?:boolean;repostOf?:string;quoteOf?:string;};type Rules={timeMode:TimeMode;olderDays:number;yearFrom:number;yearTo:number;protectDays:number;posts:boolean;replies:boolean;reposts:boolean;quotes:boolean;community:boolean;mediaPhotos:boolean;mediaVideos:boolean;mediaGifs:boolean;mediaText:boolean;postsLikesMax:number;repliesLikesMax:number;repliesMax:number;deleteWords:string[];keepWords:string[];replyHandles:string[];olderDate:string;protectDate:string;repostOf:string;topic:string;skipMentions:boolean;keepThreads:boolean;keepProfilePin:boolean;keepMedia:boolean;};/*@A*/
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
/*@@B*/ const POOL:Post[]=[];const BASE:Rules={timeMode:"none",olderDays:365,olderDate:"",yearFrom:2023,yearTo:2026,protectDays:0,protectDate:"",posts:false,replies:false,reposts:false,quotes:false,community:false,mediaPhotos:false,mediaVideos:false,mediaGifs:false,mediaText:false,postsLikesMax:-1,repliesLikesMax:-1,repliesMax:-1,deleteWords:[],keepWords:[],replyHandles:[],repostOf:"",topic:"",skipMentions:false,keepThreads:false,keepProfilePin:true,keepMedia:false,};/*@A*/
//~@@41@@
/*@@A*/ /*@A*/
//~@@42@@
/*@@A*/ /*@A*/
//~@@43@@
/*@@A*/ /*@A*/
//~@@44@@
/*@@A*/ /*@A*/
//~@@45@@
/*@@A*/ /*@A*/
//~@@46@@
/*@@A*/ const STEP_META:Record<Step,{n:number;label:string;heading:string;hint:string}>={signin:{n:1,label:"Sign in",heading:"Sign in to X",hint:"You sign in once, yourself, in the bot's own browser. The bot never sees your password."},archive:{n:2,label:"Archive",heading:"Get your archive",hint:"One click. X emails the file in about 1–3 days, and the bot loads it for you."},pick:{n:3,label:"Pick",heading:"Pick what goes",hint:"Start with a quick cleanup or set your own rules."},review:{n:4,label:"Review",heading:"Review your cleanup",hint:"Check the totals, pick Free or Fast, download the list, then approve once."},run:{n:5,label:"Run",heading:"Running",hint:"It runs on its own at X's pace. You can close this."},};/*@A*/
//~@@47@@
/*@@A*/ /*@A*/
//~@@48@@
/*@@A*/ /*@A*/
//~@@49@@
/*@@A*/ /*@B*/
//^@@50@@
/*@@B*/ /*@A*/
//~@@51@@
/*@@A*/ export default function App(){const theme=useGrokTheme();const _s0:CSSProperties={fontSize:14,color:theme.text.secondary,lineHeight:1.5};/*@B*/
//^@@52@@
/*@@B*//*@A*/
//~@@53@@
/*@@A*//*@B*/
//^@@54@@
/*@@B*//*@A*/
//~@@55@@
/*@@A*/const _s9:CSSProperties={fontSize:13,color:theme.text.tertiary};const _s10:CSSProperties={display:"flex",flexDirection:"column",gap:8};/*@A*/
//~@@56@@
/*@@A*//*@B*/
//^@@57@@
/*@@B*/const _s14:CSSProperties={minWidth:0};const pool=POOL;const[step,setStep]=useState<Step>(START_STEP);const[phase,setPhase]=useState<HomePhase>(START_PHASE);const[runPhase,setRunPhase]=useState<RunPhase>(START_RUN);const[rules,setRules]=useState<Rules>(BASE);/*@A*/
//~@@58@@
/*@@A*//*@B*/
//^@@59@@
/*@@B*//*@A*/
//~@@60@@
/*@@A*//*@B*/
//^@@61@@
/*@@B*//*@A*/
//~@@62@@
/*@@A*//*@B*/
//^@@63@@
/*@@B*//*@A*/
//~@@64@@
/*@@A*/const[likesLast,setLikesLast]=useState({posts:5,replies:5});/*@B*/
//^@@65@@
/*@@B*/const[recentOnly,setRecentOnly]=useState(false);/*@B*/
//^@@66@@
/*@@B*/const[failedIds,setFailedIds]=useState<string[]>([]);const[narrow,setNarrow]=useState(false);const[barHidden,setBarHidden]=useState(false);/*@A*/
//~@@67@@
/*@@A*/useEffect(()=>{if(!narrow||step==="review"){setBarHidden(false);return;} let lastY=window.scrollY;let stopTimer:ReturnType<typeof window.setTimeout>|undefined;const onScroll=()=>{const y=window.scrollY;if(y>lastY+2&&y>24)setBarHidden(true);else if(y<lastY-2)setBarHidden(false);lastY=y;if(stopTimer!==undefined)window.clearTimeout(stopTimer);stopTimer=window.setTimeout(()=>setBarHidden(false),450);};window.addEventListener("scroll",onScroll,{passive:true});return()=>{window.removeEventListener("scroll",onScroll);if(stopTimer!==undefined)window.clearTimeout(stopTimer);};},[narrow,step]);/*@A*/
//~@@68@@
/*@@A*/useEffect(()=>{setLikesLast((prev)=>({posts:rules.postsLikesMax>=0?rules.postsLikesMax:prev.posts,replies:rules.repliesLikesMax>=0?rules.repliesLikesMax:prev.replies,}));},[rules.postsLikesMax,rules.repliesLikesMax]);/*@B*/
//^@@69@@
/*@@B*//*@A*/
//~@@70@@
/*@@A*/const scanned=pool.length;/*@A*/
//~@@71@@
/*@@A*//*@B*/
//^@@72@@
/*@@B*/const failedCount=failedIds.length;/*@B*/
//^@@73@@
/*@@B*//*@A*/
//~@@74@@
/*@@A*//*@B*/
//^@@75@@
/*@@B*//*@A*/
//~@@76@@
/*@@A*//*@B*/
//^@@77@@
/*@@B*//*@A*/
//~@@78@@
/*@@A*/const scrollToId=(id:string)=>{const el=document.getElementById(id);if(el)el.scrollIntoView({behavior:"smooth",block:"start"});};/*@A*/
//~@@79@@
/*@@A*/const goStep=(id:Step)=>{setStep(id);};/*@A*/
//~@@80@@
/*@@A*//*@B*/
//^@@81@@
/*@@B*/const primary=(():{label:string;action:()=>void;disabled?:boolean}|null=>{if(step==="signin")return null;if(step==="archive")return null;/*@A*/
//~@@82@@
/*@@A*/ if(step==="pick")return{label:"Next: review my list →",action:()=>goStep("review"),disabled:true/*@B*/
//^@@83@@
/*@@B*/};if(step==="review")return null;if(failedCount>0)return{label:"Open failure tray",action:()=>scrollToId("run-tray")};return null;})();const heading=step==="run"&&runPhase==="done"?"Done":STEP_META[step].heading;const hint=step==="run"&&runPhase==="done"?"Here is what was verified, plus optional cleanup on Google and Wayback.":STEP_META[step].hint;/*@A*/
//~@@84@@
/*@@A*/const panel:CSSProperties={borderRadius:16,border:`1px solid ${theme.border.default}`,background:theme.bg.subtle,padding:24,};/*@A*/
//~@@85@@
/*@@A*/const tapLine=(sentence:string)=>(<div style={{fontSize:14,color:theme.text.secondary,lineHeight:1.5,marginTop:10}}>{sentence}</div>);const xDownloadLink=(<div style={{fontSize:13,color:theme.text.secondary,marginTop:10,lineHeight:1.45}}>Or request it yourself on <TextLink href="https://x.com/settings/download_your_data">X's Download your data page</TextLink> (opens in your own browser).</div>);const recentOnlyOffer=(<div style={_s10}><div style={_s0}>Optional, while you wait for the archive: start with your recent posts only (about the last 3,200). This is not your full history, and it still needs a preview and one Approve.</div><div>{tapLine("Start with recent posts only with the tap card in the chat.")}</div></div>);/*@A*/
//~@@86@@
/*@@A*//*@B*/
//^@@87@@
/*@@B*//*@A*/
//~@@88@@
/*@@A*//*@B*/
//^@@89@@
/*@@B*/return(<Page title="X Post Cleaner" width="full" summary="Free. No card. Nothing to cancel. Sign in, get your archive, pick what goes, approve once." palette={["#6EC1FF","#4AA3E0","#B8DFFF"]}><style>{`.xpc-wrap{max-width: 1440px;margin: 0 auto;padding: 4px 12px 96px;box-sizing: border-box}.xpc-stepper{display: flex;align-items: center;gap: 6px;margin: 0 0 20px}.xpc-step{display: flex;align-items: center;gap: 8px;min-width: 0;background: none;border: 0;padding: 6px 4px;cursor: pointer;text-align: left;font: inherit;color: inherit}.xpc-step[disabled]{cursor: default;opacity: 0.45}.xpc-num{width: 26px;height: 26px;border-radius: 999px;display: inline-flex;align-items: center;justify-content: center;font-size: 13px;font-weight: 600;flex-shrink: 0}.xpc-step-label{font-size: 14px;font-weight: 600;white-space: nowrap}.xpc-shell{display: grid;grid-template-columns: 200px minmax(0, 1fr) 280px;gap: 32px;align-items: start}.xpc-rail, .xpc-summary{position: sticky;top: 24px}.xpc-quick{display: grid;grid-template-columns: repeat(3, minmax(0, 1fr));gap: 12px}.xpc-groups{display: grid;grid-template-columns: repeat(2, minmax(0, 1fr));gap: 12px;align-items: start}.xpc-groups-col{display: flex;flex-direction: column;gap: 12px;min-width: 0}.xpc-likes-pair{display: grid;grid-template-columns: 1fr 1fr;gap: 16px;align-items: start}.xpc-likes-pick{min-width: 0;width: 100%;box-sizing: border-box}.xpc-list{max-height: 640px;overflow: auto;border-radius: 16px}.xpc-row{display: grid;grid-template-columns: auto minmax(0, 1fr) 220px;gap: 16px;align-items: start;padding: 16px 20px}.xpc-keep{display: inline-flex;align-items: center;gap: 6px;border-radius: 999px;padding: 6px 12px;font-size: 13px;font-weight: 600;cursor: pointer;white-space: nowrap;font-family: inherit}.xpc-text{font-size: 15px;line-height: 1.45;display: -webkit-box;-webkit-line-clamp: 2;-webkit-box-orient: vertical;overflow: hidden}.xpc-about{font-size: 13.5px;margin-top: 4px;white-space: nowrap;overflow: hidden;text-overflow: ellipsis}.xpc-verdict{text-align: right}.xpc-totals{width: auto;max-width: 420px;border-collapse: collapse;font-size: 14px;line-height: 1.3}.xpc-totals th, .xpc-totals td{padding: 5px 16px 5px 0;vertical-align: top}.xpc-totals th:not(:first-child), .xpc-totals td:not(:first-child){text-align: right;padding-left: 20px;padding-right: 0}.xpc-engage{display: flex;flex-direction: column;gap: 8px}.xpc-engage-row{display: flex;align-items: stretch;gap: 8px}.xpc-engage-off, .xpc-engage-step, .xpc-engage-chip{min-height: 36px;border-radius: 10px;cursor: pointer;font-size: 13px;font-weight: 600}.xpc-engage-off{padding: 0 12px;flex: 0 0 auto}.xpc-engage-step{min-width: 36px;padding: 0;flex: 0 0 36px;font-size: 16px;line-height: 1}.xpc-engage-num{flex: 1 1 96px;min-width: 72px;min-height: 36px;border-radius: 10px;font-size: 15px;font-weight: 600;text-align: center;padding: 0 8px;box-sizing: border-box}.xpc-engage-chips{display: flex;flex-wrap: wrap;gap: 8px}.xpc-engage-chip{padding: 0 12px}.xpc-engage-off:disabled, .xpc-engage-step:disabled, .xpc-engage-chip:disabled, .xpc-engage-num:disabled{cursor: not-allowed}@media (max-width: 1280px){.xpc-quick{grid-template-columns: repeat(2, minmax(0, 1fr))}}@media (max-width: 1100px){.xpc-shell{grid-template-columns: minmax(0, 1fr)}.xpc-rail, .xpc-summary{display: none}}@media (max-width: 760px){.xpc-quick, .xpc-groups{grid-template-columns: minmax(0, 1fr)}.xpc-likes-pair{grid-template-columns: minmax(0, 1fr)}.xpc-row{grid-template-columns: auto minmax(0, 1fr)}.xpc-verdict{grid-column: 2;text-align: left}.xpc-step-label{font-size: 12px}.xpc-wrap{padding: 0 0 112px}}.xpc-wrap-pickbar{padding-bottom: calc(80px + env(safe-area-inset-bottom, 0px))}@media (max-width: 760px){.xpc-wrap-pickbar{padding: 0 0 calc(80px + env(safe-area-inset-bottom, 0px))}}.xpc-nextbar{position: fixed;left: 0;right: 0;bottom: 0;z-index: 50;display: flex;align-items: center;justify-content: center;gap: 10px;box-sizing: border-box;height: calc(48px + env(safe-area-inset-bottom, 0px));max-height: calc(48px + env(safe-area-inset-bottom, 0px));padding: 0 12px env(safe-area-inset-bottom, 0px);transform: translateY(0);transition: transform 0.2s ease, opacity 0.2s ease}.xpc-nextbar-counts{font-size: 13px;line-height: 1.2;white-space: nowrap;overflow: hidden;text-overflow: ellipsis;min-width: 0}.xpc-nextbar-hide{transform: translateY(100%);opacity: 0;pointer-events: none}.xpc-kinds-grid{display: grid;grid-template-columns: 1fr 1fr;gap: 8px 24px;align-items: start}.xpc-tiers{display: grid;grid-template-columns: repeat(3, minmax(0, 1fr));gap: 12px;margin-top: 16px}.xpc-tier{border-radius: 14px;padding: 16px 18px;display: flex;flex-direction: column;gap: 8px;min-width: 0}h1{color: #8BE9FF !important;text-shadow: 0 0 6px rgba(110, 193, 255, 0.95), 0 0 18px rgba(74, 163, 224, 0.55), 0 0 36px rgba(110, 193, 255, 0.35)}@media (max-width: 760px){.xpc-kinds-grid, .xpc-tiers{grid-template-columns: minmax(0, 1fr)}}`}</style><div className={narrow&&primary&&step!=="review"?"xpc-wrap xpc-wrap-pickbar":"xpc-wrap"} style={{fontFamily:theme.font.family,color:theme.text.primary}}>{SIGNED_IN_HANDLE!==""&&(<div style={{fontSize:13,color:theme.text.secondary,margin:"0 0 8px",lineHeight:1.45}}>{`Signed in as @${SIGNED_IN_HANDLE.replace(/^@/,"")}`}</div>)}<div className="xpc-stepper" role="navigation" aria-label="Cleanup steps">{(["signin","archive","pick","review","run"]as Step[]).map((id,i)=>{const meta=STEP_META[id];const active=step===id;const locked=(id==="run"||id==="review")/*@B*/
//^@@90@@
/*@@B*/;const label=id==="run"&&runPhase==="done"?"Done":meta.label;return(<div key={id} style={{display:"flex",alignItems:"center",gap:6,flex:i<4?1:"0 0 auto",minWidth:0}}><button type="button" className="xpc-step" disabled={locked||id==="pick"/*@A*/
//~@@91@@
/*@@A*/} onClick={()=>goStep(id)} aria-current={active?"step":undefined}><span className="xpc-num" style={{background:active?theme.fill.primary:theme.fill.secondary,color:active?theme.text.onPrimary:theme.text.secondary}}>{meta.n}</span><span className="xpc-step-label" style={{color:active?theme.text.primary:theme.text.secondary}}>{label}</span></button>{i<4&&<div style={{flex:1,height:1,background:theme.border.default,minWidth:12}}/>}</div>);})}</div>{PAGE_STATUS&&(PAGE_STATUS.lead!==""||PAGE_STATUS.text!=="")&&(<div role="status" style={{margin:"0 0 20px",padding:"12px 14px",borderRadius:12,border:`1px solid ${theme.border.default}`,background:PAGE_STATUS.tone==="ok"?theme.fill.successSubtle:PAGE_STATUS.tone==="info"?theme.fill.accentSubtle:theme.bg.subtle}}>{PAGE_STATUS.lead!==""&&(<div style={{fontSize:14,fontWeight:650,color:PAGE_STATUS.tone==="ok"?theme.text.success:PAGE_STATUS.tone==="info"?theme.text.accent:theme.text.warning}}>{PAGE_STATUS.lead}</div>)}{PAGE_STATUS.text!==""&&(<div style={{fontSize:14,color:theme.text.secondary,lineHeight:1.45,marginTop:PAGE_STATUS.lead!==""?4:0}}>{PAGE_STATUS.text}</div>)}</div>)}<div className="xpc-shell">{null/*@A*/
//~@@92@@
/*@@Ac*/}<main style={_s14}><div style={{marginBottom:22}}><h2 style={{margin:0,fontSize:theme.font.heading2.fontSize,lineHeight:theme.font.heading2.lineHeight,fontFamily:theme.font.family,color:theme.text.primary,fontWeight:650}}>{heading}</h2><p style={{margin:"6px 0 0",fontSize:15,lineHeight:1.5,color:theme.text.secondary}}>{hint}</p>{null/*@B*/
//^@@93@@
/*@@Bc*/}</div>{step==="signin"&&(<div style={{display:"flex",flexDirection:"column",gap:20}}><div style={_s0}>Sign in in the X window in the chat. If you already signed in, you're set.</div>{null/*@A*/
//~@@94@@
/*@@Ac*/}</div>)}{step==="archive"&&(<div style={{display:"flex",flexDirection:"column",gap:20}}><div id="arc-get" style={{display:"flex",flexDirection:"column",gap:16}}>{phase==="choose"&&(<><div style={{...panel,background:theme.fill.accentSubtle,padding:"28px 28px"}}><Rows rows={[{title:"1. Request",detail:"The bot taps Download your data on X, in its own signed-in browser."},{title:"2. Wait",detail:"X emails a link, usually in 1–3 days. While you wait, choose what to delete: old posts, replies with few likes, reposts, and more."},{title:"3. Load",detail:"The bot downloads the file and loads it here. You never handle the ZIP."},]}/><div style={{marginTop:18}}>{xDownloadLink}</div></div><div role="button" tabIndex={0} onClick={()=>setPhase("manual")} style={{...panel,minHeight:80,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",gap:4,cursor:"pointer",borderStyle:"dashed"}}><span style={{fontSize:15,color:theme.text.secondary}}>Already have the file? Drop your archive here</span><span style={_s9}>ZIP or tweets.js · read on the bot's computer</span></div>{recentOnlyOffer}</>)}{(phase==="grabbing"||phase==="waiting")&&(<div style={_s0}>Your archive has been requested. X usually takes 1 to 3 days. The bot will pull it in automatically and let you know when it's ready. Meanwhile, set up your rules.</div>)}{phase==="manual"&&(<><div style={{...panel,minHeight:100,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",gap:6,borderStyle:"dashed"}}><span style={{fontSize:16,color:theme.text.secondary}}>Drop your archive here</span><span style={_s9}>or click to browse · ZIP or tweets.js</span></div><div><Button label="Let the bot fetch it instead" variant="quiet" onClick={()=>setPhase("choose")}/></div></>)}{phase==="ready"&&(<>{recentOnly?(<Callout tone="info" lead="Recent only · not your full history">Your recent posts (about the last 3,200 X can show). Older posts are not in this list. Your official archive is still the way to clean your full history.</Callout>):(<Callout tone="success" lead="Archive loaded">{`${scanned.toLocaleString("en-US")} posts found. Next, choose what goes.`}</Callout>)}{recentOnly&&(<div>{tapLine("Wait for the full archive with the tap card in the chat.")}</div>)}</>)}</div>{null/*@A*/
//~@@95@@
/*@@Ac*/}</div>)}{null/*@A*/
//~@@96@@
/*@@Ac*/}{null/*@B*/
//^@@97@@
/*@@Bc*/}{null/*@B*/
//^@@98@@
/*@@Bc*/}</main>{null/*@B*/
//^@@99@@
/*@@Bc*/}</div></div>{null/*@B*/
//^@@100@@
/*@@Bc*/}</Page>);}