import { describe,it,expect } from "vitest";
import { MAX_BATCH_ITEMS,BATCH_STATUS,batchActions,batchReducer,createBatchItems,createInitialBatchState,selectNextQueuedItem } from "./batchState.js";
const files=n=>Array.from({length:n},(_,i)=>({name:`${i}.png`}));
const items=n=>createBatchItems(files(n),{localIdFactory:(_,i)=>`local-${i}`,jobIdFactory:(_,i)=>i.toString(16).padStart(32,"0")});
describe("batch state",()=>{
 it("caps admission at ten and processes sequentially",()=>{let s=batchReducer(createInitialBatchState(),batchActions.admit(items(12)));expect(s.items).toHaveLength(MAX_BATCH_ITEMS);expect(selectNextQueuedItem(s).localId).toBe("local-0");s=batchReducer(s,batchActions.processing("local-0"));expect(selectNextQueuedItem(s)).toBeNull();});
 it("retry retains File but allocates a new job id",()=>{const [x]=items(1);let s=batchReducer(createInitialBatchState(),batchActions.admit([x]));s=batchReducer(s,batchActions.processing(x.localId));s=batchReducer(s,batchActions.failed(x.localId,"bad"));const before=s.items[0],next="f".repeat(32);s=batchReducer(s,batchActions.retry(x.localId,next));expect(s.items[0]).toMatchObject({file:before.file,clientJobId:next,status:BATCH_STATUS.QUEUED,error:null});});
 it("selects first success without stealing an existing ready selection",()=>{const xs=items(2);let s=batchReducer(createInitialBatchState(),batchActions.admit(xs));s=batchReducer(s,batchActions.processing("local-0"));s=batchReducer(s,batchActions.ready("local-0",{width:1,height:1}));expect(s.selectedLocalId).toBe("local-0");s=batchReducer(s,batchActions.processing("local-1"));s=batchReducer(s,batchActions.ready("local-1",{width:1,height:1}));expect(s.selectedLocalId).toBe("local-0");});
});
