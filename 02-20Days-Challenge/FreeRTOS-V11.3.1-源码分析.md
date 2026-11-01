# FreeRTOS Kernel V11.3.1 源码分析报告

> 分析对象：`FreeRTOS-Kernel-V11.3.1` 官方发行版（非 git 仓库，无本地改动）
> 视角：**设计原理**为主，**功耗（低功耗）**为专题重点
> 所有行号均来自实际源码阅读；标注为 `文件:行号`

---

## 一、全局地图

| 层 | 内容 | 规模 |
|---|---|---|
| 内核核心 | `tasks.c` `queue.c` `timers.c` `event_groups.c` `stream_buffer.c` `list.c` `croutine.c` | 约 35.6k 行（含头文件） |
| 公共头文件 | `include/` —— `FreeRTOS.h`（配置与默认值）、`task.h`、`queue.h`、`semphr.h` 等 | 24 个头文件 |
| 移植层 | `portable/` —— 26 个编译器/架构变体 | 913 文件，159 个 `port.c` |

文件规模（由大到小）：`tasks.c` 8967、`include/task.h` 3899、`queue.c` 3400、`include/FreeRTOS.h` 3371、`stream_buffer.c` 1757、`timers.c` 1345、`event_groups.c` 887、`list.c`、`croutine.c`。

**一句话概括设计哲学**：整个内核只建立在**一条双向链表**和**一种同步对象（队列）**这两个原语之上——任务状态、延时、优先级轮转、事件等待全靠 `List_t`；信号量、互斥量、队列集、软件定时器消息全靠 `Queue_t`。

---

## 二、设计基石：`list.c` / `include/list.h`

`list.c` 只有 4 个函数（`vListInitialise`、`vListInitialiseItem`、`vListInsertEnd`、`vListInsert`、`uxListRemove`），却支撑了整个内核。

### 2.1 结构

- `ListItem_t`（`list.h:154`）：`xItemValue`（排序键）、`pxNext`/`pxPrevious`（双向）、`pvOwner`（指回 TCB）、`pxContainer`（**记录自己挂在哪条链表**）。
- `List_t`（`list.h:172`）：`uxNumberOfItems`、`pxIndex`（遍历游标）、`xListEnd`（哨兵项，`xItemValue = portMAX_DELAY`，永远在末尾）。

### 2.2 三个关键设计决策

1. **`pxContainer` 让移除变成 O(1)**：`uxListRemove`（`list.c:222`）不需要搜索链表，直接用 `pxItemToRemove->pxContainer` 得到链表头（`list.c:227`）。这是任务能从"事件表"和"状态表"同时被摘除的前提。

2. **哨兵替代 NULL 判断**：`vListInitialise`（`list.c:48`）把 `xListEnd.pxNext/pxPrevious` 指向自身、值设为 `portMAX_DELAY`。于是"链表为空"与"链表末尾"用同一套指针逻辑处理，插入排序循环不必额外判空（`list.c:186`）。

3. **`pxIndex` 游标实现 O(1) 时间片轮转**：`listGET_OWNER_OF_NEXT_ENTRY`（`list.h:286`）把游标推进一格并返回该项的 `pvOwner`，到哨兵则回卷到第一个。调度器每次选任务就调用它（`tasks.c:205-206`），**同优先级任务天然获得均等 CPU 份额**，无需额外数据结构。

### 2.3 排序语义

`vListInsert`（`list.c:150`）按 `xItemValue` 升序插入；值相同时新项插到**后面**（`list.c:186` 的 `<=` 比较），保证同优先级 FIFO 公平。延时链表按键值=唤醒时刻排序，因此"表头就是最早要醒的任务"，`xTaskIncrementTick` 只需看表头（`tasks.c:4904`）。

---

## 三、任务管理 `tasks.c`

### 3.1 TCB 的字段布局有硬约束

```c
typedef struct tskTaskControlBlock {           /* tasks.c:377 */
    volatile StackType_t * pxTopOfStack;       /* 必须是第一个成员 (tasks.c:379) */
    #if ( portUSING_MPU_WRAPPERS == 1 )
        xMPU_SETTINGS xMPUSettings;            /* 必须是第二个成员 (tasks.c:382) */
    #endif
    ListItem_t xStateListItem;                 /* tasks.c:389 */
    ListItem_t xEventListItem;                 /* tasks.c:390 */
    ...
```

- `pxTopOfStack` 首成员：上下文切换汇编只保存/恢复**一个指针**（`portable/GCC/ARM_CM4F/port.c:521` 的 `str r0,[r2]`），寄存器值都在栈帧里。改变布局会直接破坏所有 `port.c`。
- `xEventListItem` 的键值被编码为 `configMAX_PRIORITIES - uxPriority`（`tasks.c:1929`）——**优先级越高，键值越小**，于是事件等待表按优先级降序排列，取表头即最高优先级等待者（`tasks.c:5420`）。

### 3.2 就绪链表与"摊还 O(1)"选任务

`pxReadyTasksLists[configMAX_PRIORITIES]`（`tasks.c:478`），`uxTopReadyPriority`（`tasks.c:507`）缓存最高就绪优先级：

```c
#define taskRECORD_READY_PRIORITY( uxPriority ) \      /* tasks.c:186 */
    if( ( uxPriority ) > uxTopReadyPriority )       \
    { uxTopReadyPriority = ( uxPriority ); }
```

该缓存**只升不降**，所以选任务时通常一次命中；只有当该优先级链表恰好空时才向下扫描（`tasks.c:199-211`，内含 `--uxTopPriority` 循环）。这就是 FreeRTOS 声称的 O(1) 调度——严格说是**摊还 O(1)**。

> **常见误解纠正**：`configUSE_PORT_OPTIMISED_TASK_SELECTION`（32 位位图 + CLZ 指令的"真正" O(1)）在本版中**默认为 0**（`FreeRTOS.h:2803-2804`），且在 SMP 下被 `#error` 禁用（`FreeRTOS.h:2917-2918`）。它开启后要求 `configMAX_PRIORITIES <= 32`（`portable/GCC/ARM_CM4F/portmacro.h:161-171`）。

### 3.3 双延时链表的精妙之处

`xDelayedTaskList1` / `xDelayedTaskList2` 与两个指针（`tasks.c:479-482`）。

**动机**：唤醒时刻 `xTimeToWake = xTickCount + xTicksToDelay` 是**无符号加法，会回绕**。如果把所有任务放一条表，回绕后的时刻会排到表头，比较逻辑必须做回绕判断（繁琐且易错）。FreeRTOS 的解法是**物理隔离**：未回绕的放一张表、已回绕的放另一张表（`tasks.c:8738-8755`），于是任意时刻**只需在一张表内做普通数值比较**（`tasks.c:4900-4914`）。tick 计数回绕时仅交换两个指针，并断言旧表已空（`tasks.c:266-278`、`tasks.c:4864-4867`）。

### 3.4 阻塞与唤醒

- `prvAddCurrentTaskToDelayedList`（`tasks.c:8685`）：先摘出就绪表并复位优先级位（`8703-8712`）；若 `portMAX_DELAY` 且允许无限阻塞 → 移入 `xSuspendedTaskList`（`8718-8725`）；否则插入延时表并可能更新 `xNextTaskUnblockTime`（`8738-8755`）。
- `xTaskIncrementTick`（`tasks.c:4831`）：调度器挂起时**不加 tick**，改为 `xPendedTicks++`（`5042` 附近），等 `xTaskResumeAll` 统一补跑（`4155-4182`）。正常时 tick++，回绕则换表，然后循环摘延时表头直至未到期（`4880-4935`）。
- `xTaskDelayUntil`（`tasks.c:2414`）用**绝对唤醒时刻**为基准（`2438-2466`），因此周期不漂移；`vTaskDelay` 则是"从现在起再等"。

### 3.5 优先级继承（互斥量防优先级翻转）

- **继承**：任务取互斥量失败阻塞时，`queue.c:1795` → `xTaskPriorityInherit`（`tasks.c:6747`）。若持有者优先级更低，就把持有者**临时提升**到申请者优先级（`6808`/`6815`），并改写其 `xEventListItem` 键值、必要时换就绪链表（`6774-6788`）；原优先级保存在 `uxBasePriority`（`tasks.c:1914-1918`）。
- **归还**：`xTaskPriorityDisinherit`（`tasks.c:6848`）中**只有 `uxMutexesHeld == 0` 才真正降级**（`6873-6878`）。这解决了"持有者被临时提升后又取了第二个互斥量"的嵌套场景——必须等最后一个互斥量归还才恢复，否则会在持锁中途被抢走 CPU。

### 3.6 SMP（`configNUMBER_OF_CORES > 1`）带来的变化

V11 的 SMP 是**改造单核代码**实现的，不是重写：

- 全局 `pxCurrentTCB` 单指针（`tasks.c:465`）→ `pxCurrentTCBs[]` 数组（`tasks.c:470`），再用 `#define pxCurrentTCB` 取本核句柄，**上层代码几乎不变**。
- 新增 `xTaskRunState`（`tasks.c:394`）：`>= 0` 表示正在哪个核运行、`-1` 未运行、`-2` 已决定让出（`tasks.c:321/324/331`）。
- 临界区与挂起调度器需要**双锁**：`vTaskSuspendAll` 先关中断 → 取任务锁 → `prvCheckForRunStateChange`（可能被换核，需重取 coreID）→ 取 ISR 锁（`tasks.c:3944-3986`）。单核版本不需要临界区，因为"能重新调度"就证明计数已归零（`tasks.c:3895-3925`）——这个论证**跨核不成立**。
- `configUSE_PORT_OPTIMISED_TASK_SELECTION` 在 SMP 下无意义（一个核的位图无法表达全局），故被禁用。

### 3.7 `uxSchedulerSuspended` 就是嵌套深度

它既是"调度器挂起计数"（`tasks.c:3928` 自增、`4088` 自减、`4086` 断言非零），也是 `vTaskSuspendAll/xTaskResumeAll` 的嵌套层数。

**重要语义区分**（易混淆）：
- `taskENTER_CRITICAL()` 只屏蔽中断/其它核，**不阻止本核发生上下文切换**。
- `vTaskSuspendAll()` 才真正冻结调度，因此它要求当前核临界区计数为 0（`tasks.c:3958`）。

---

## 四、队列与同步原语 `queue.c` / `semphr.h`

### 4.1 一个结构体演化了整个同步对象家族

```c
typedef struct QueueDefinition {          /* queue.c:103 */
    int8_t * pcHead;                      /* queue.c:105 */
    ...
    #define uxQueueType pcHead            /* queue.c:65 —— 宏别名充当类型标签 */
    union {                               /* queue.c:108-112 */
        QueueSetHandle_t xQueueSet;
        SemaphoreHandle_t xSemaphore;
    } u;
```

**技巧**：`pcHead` 被 `#define` 成 `uxQueueType`（类型标签），而 `u` 是联合体。互斥量把 `pcHead` 置 NULL 作标记（`queue.c:66,626-629`），从而合法使用 `u.xSemaphore`（含 `xMutexHolder`/`uxRecursiveCallCount`）——**零额外空间**实现类型区分。

### 4.2 环形缓冲 + 双等待表

- 存储区 `pcTail = pcHead + uxLength * uxItemSize`，**末尾多一个字节作越界哨兵**（`queue.c:79,320`）。
- `pcWriteTo` 指向下一个可写位置（初值 `pcHead`，`queue.c:322`）；`pcReadFrom` 指向**上一次读出**的位置（初值指向最后一项），因此接收时**先自增再拷贝**（`queue.c:80,2504-2506`）。
- `xTasksWaitingToSend` / `xTasksWaitingToReceive` 两个按优先级排序的事件表（`queue.c:114-115`）。

**设计原理**：把"有空间"与"有数据"两个约束**解耦**——生产者只挂 send 表、消费者只挂 receive 表。唤醒时不必遍历，直接取对应表头即为最高优先级等待者；两张表按优先级排序，取头是 O(1)。

### 4.3 `uxItemSize == 0` 是"降级"开关

```c
if( pxQueue->uxItemSize != ( UBaseType_t ) 0 )   /* queue.c:2405 */
{ /* memcpy 拷贝数据 */ }
```

当 `uxItemSize == 0`（`semphr.h:41` 定义信号量时用 0），发送只递增 `uxMessagesWaiting`、接收什么都不做（`queue.c:2479`）。**队列因此"退化成"纯计数同步原语——这就是信号量的全部实现**。信号量、二值信号量、计数信号量、互斥量都只是带不同参数的队列（`semphr.h:167,298,460,735,1025` 全是宏）。

### 4.4 临界区策略：短关中断 + 挂起调度器

临界区内只做"判满/判空 + 拷贝 + 计数"（`queue.c:974,1535`），**绝不阻塞**。

队列快路径失败后才 `vTaskSuspendAll() + prvLockQueue()`（`queue.c:1117-1118`）。`prvLockQueue` 的必要性在于：`taskENTER_CRITICAL` **拦不住已经进入的 ISR**，而调度器挂起期间 ISR 若直接改事件表会破坏"只进 pending ready list"的约定。于是用 `cRxLock`/`cTxLock` 让 ISR **只记账、不改表**（`queue.c:252-269`），解锁时批量补唤醒（`prvUnlockQueue`，`queue.c:2500-2596`）。

### 4.5 队列集

队列集本质就是一个普通队列，其元素是 `sizeof(Queue_t *)` 的成员句柄（`queue.c:3186`）。成员队列收到数据时，`prvNotifyQueueSetContainer` 把"哪个队列可读"的**句柄当作数据项压入集合**（`queue.c:3366`），取出完全复用 `xQueueReceive`（`queue.c:3314`）。

---

## 五、其它内核组件

### 5.1 软件定时器 `timers.c`（含功耗要点）

- 定时器不是中断，而是一个**守护任务** `prvTimerTask`：从 `xTimerQueue` 取命令（`timers.c:943`），用 `prvGetNextExpireTime` 算出最近到期时刻（`timers.c:842-865`），然后**定时阻塞等待**：

```c
vQueueWaitForMessageRestricted( xTimerQueue,             /* timers.c:818 */
                                ( xNextExpireTime - xTimeNow ),
                                xListWasEmpty );
```

- `prvProcessTimerOrBlockTask`（`timers.c:780`）必须在 `vTaskSuspendAll()` 保护下取时间并判断（`785,791-801`），避免与 tick 中断竞争；`xTimeNow < xLastTime` 判定 tick 回绕后调用 `prvSwitchTimerLists`（`timers.c:876-878`）处理残余并换表。
- **守护任务的三步循环**（`prvTimerTask`，`timers.c:746`）：① `prvGetNextExpireTime` 取表头（**空表返回 0**，保证 tick 回绕时必然醒来重估，`timers.c:842-865`）→ ② `prvProcessTimerOrBlockTask` 判断到期或定时阻塞 → ③ `prvProcessReceivedCommands` 非阻塞排空队列（`timers.c:936-965`），按 `xMessageID` 分派 START/RESET/STOP/CHANGE_PERIOD/DELETE。
- **API 即消息**：所有 `xTimerXxx` 宏都展开为向 `xTimerQueue` 入队一个命令（`timers.h:507`）；消息体 `DaemonTaskMessage_t` = `xMessageID` + 联合体（`timers.c:107-118`）。`xTimerPendFunctionCall` 就是一条“负 ID 消息”（`timers.c:949,1285`），使任意回调能在守护任务上下文中执行——这是从 ISR 安全调用复杂函数的标准手法。
- **两个配置陷阱**：`configTIMER_QUEUE_LENGTH` 是队列深度（`timers.c:1137,1141`），**队列满时入队会阻塞至超时并返回 `pdFAIL`，命令被静默丢弃**，必须检查返回值；`configTIMER_TASK_PRIORITY` 设得过高会让长回调阻塞所有低优先级任务，设得过低则守护任务被抢占而导致定时抖动。

> ⚠ **功耗关联（重要）**：守护任务的这次"定时阻塞"会把**最近一个软件定时器的到期时刻**写进延时链表，从而成为 `xNextTaskUnblockTime`。**因此软件定时器越密集、周期越短，系统能连续睡眠的时间就越短**（详见第九章）。

### 5.2 事件组 `event_groups.c`

与队列走**不同实现路线**：不使用队列，而是 `EventBits_t uxEventBits` 位图 + `xTasksWaitingForBits` 链表。等待任务直接挂在单条链表上，唤醒时按位掩码条件筛选（配合 `vTaskRemoveFromUnorderedEventList`，`tasks.c:5567`）。这种"直接链表"做法的收益是支持**多位组合等待**（`xEventGroupWaitBits` 的 `uxBitsToWaitFor`），这是队列/信号量无法表达的语义。`xEventGroupSync` 提供会合（rendezvous）语义。

细节与三个精妙点：

- `EventBits_t` 就是一个整型（`event_groups.h:113`，宽度随 tick 类型），**高 8 位被内核占用作控制位**（`event_groups.h:43-56`）；`EventGroup_t` = `uxEventBits` + `xTasksWaitingForBits`（`event_groups.c:54-64`）。
- **等待语义记在等待者自己身上**：`xEventGroupWaitBits`（`event_groups.c:312`）挂起调度器后先 `prvTestWaitCondition` 按 OR/AND 判定（`778`）；不满足则把 `uxBitsToWaitFor | 控制位` 写进**任务自己的 `xEventListItem`**，再尾插等待链表（`394`）。控制位编码本次等待语义：`CLEAR_ON_EXIT`（`375`）、`WAIT_FOR_ALL`（`384`）。**事件组没有独立的“等待状态对象”**——每个等待者的语义都复用 TCB 已有的列表项字段，因此等待过程**零内存分配**。
- **清除动作由置位方完成**：`xEventGroupSetBits`（`547`）先做位图 `|=`（`574`），再遍历链表按控制位匹配（`590,599`），命中者以“当前位图 + UNBLOCKED 标志”写回其列表项并摘链（`626`），需 clear-on-exit 的位累积后统一清除（`637`）——因此**不存在“谁来清”的竞态**。而**超时者没有 UNBLOCKED 标志**，需要重读位图并补清（`421-437`），这正是超时路径与正常唤醒路径必须分开处理的原因。
- `xEventGroupSync`（`185`）实现会合：先置己位，若 `(原值|set) & waitFor == waitFor` 则立即返回并清位（`211-218`），否则以 `CLEAR_ON_EXIT|WAIT_FOR_ALL` 挂起（`231`）；**最后一个到达者负责唤醒其余所有等待者**。
- **为何用链表而非队列**：多个任务可能以**不同掩码**等待同一组位，且“位被取走即消费”不成立，因此无需按值排序；置位时一次遍历即可精确唤醒/清除。队列与信号量则相反——数据或令牌会被唯一取走，必须有独立的 `Queue_t` 与按优先级排序的阻塞表。
- ISR 不直接操作事件组：`xEventGroupSetBitsFromISR`（`817`）经 `xTimerPendFunctionCallFromISR` 把 `vEventGroupSetBitsCallback`（`751`）**推迟到守护任务**中执行。

### 5.3 流缓冲/消息缓冲 `stream_buffer.c`

面向**单生产者-单消费者**的字节流场景，比队列轻量：环形缓冲区 + 读/写指针 + **触发水位**（trigger level），`xStreamBufferSend` 在写入量达到水位后唤醒等待的读者。消息缓冲区 `message_buffer` 在其上附加长度头，实现变长消息。

细节：

- `StreamBuffer_t`（`stream_buffer.c:232-252`）：`volatile` 的 `xTail`/`xHead`、`xLength`、`xTriggerLevelBytes`、`xTaskWaitingToReceive`/`xTaskWaitingToSend`、`pucBuffer`、`ucFlags`（`225-227`）。
- **写函数不推进 `xHead`**：`prvWriteBytesToBuffer`（`1488`）在 `xLength - xHead` 处截断、先写尾段再回绕写头段（`1500`），**由调用方最后一次性提交**。这一设计让“消息头 + 消息体”可以分两次写入而对外保持原子性（见下）。
- `prvBytesInBuffer = (xLength + xHead - xTail) % xLength`（`1578`）。**空与满的表达式值相同**，因此可用空间恒为 `xLength - 1`（`832`）——这是环形缓冲区容量与判空判满的经典取舍。
- **“单写单读”是硬约束**：`xHead` 只由写者修改、`xTail` 只由读者修改，读出时**不搬移数据**。由于只允许一个写者和一个读者（`893,1118`），唤醒用 `xTaskNotifyIndexed` **单播**即可（`150-166`），省掉一个完整的内核对象。
- **触发水位** `xTriggerLevelBytes`（`237`）不控制“能否写”，只决定“攒够多少字节才唤醒读者”（`1599`），把逐字节到达合并为一次唤醒——**这是减少上下文切换与功耗的关键设计**（批处理语义要求水位严格大于单次写入量）。
- **消息缓冲的原子性**：先写长度头 `sbBYTES_TO_STORE_MESSAGE_LENGTH`（`222`，等于 `sizeof(configMESSAGE_BUFFER_LENGTH_TYPE)`）于 `1036`；因为写函数不推进 `xHead`，头与体是“原子拼接”，最后一次性提交（`1058`）——**读者永远看不到半条消息**。读侧先取长度（`1301`）再取体（`1336`），并要求 `xBytesAvailable` 大于长度头（`1196`）。
- ISR 路径：`xStreamBufferSendCompletedFromISR`（`1410`）在临界区内用 `xTaskNotifyIndexedFromISR` 通知唯一等待者并清句柄——ISR 只做最短动作。

### 5.3.1 同步对象谱系（为什么需要四种）

| 对象 | 等待谓词 | 数据语义 | 阻塞表 | ISR 交接方式 |
|---|---|---|---|---|
| 队列 | “有项可取” | 有数据副本，多写多读 | 独立 `Queue_t`，两张按优先级排序的表 | 入队 + `*pxHigherPriorityTaskWoken` |
| 信号量 | “计数 > 0” | 无数据（`uxItemSize == 0`） | 同上（复用队列） | 同上 |
| 事件组 | “掩码条件成立” | 位图，**无消费、显式清除**、可 OR/AND | 复用 TCB 的 `xEventListItem`，单条无序链表 | 推迟到守护任务（`xTimerPendFunctionCallFromISR`） |
| 流缓冲 | “字节数达水位” | 环形字节流，单写单读 | 仅两个等待者句柄（非链表） | `xTaskNotifyIndexedFromISR` 单播 |

**共同点**：都用“挂起调度器 / 短临界区”保证一致性；等待者一律复用 TCB 里已有的 `xEventListItem` 字段挂链；唤醒统一走 `vTaskRemoveFromUnorderedEventList` 或 `xTaskNotify`；ISR 一律只做“入队 / 置位 / 通知”这类最短动作。

**差异的根源是等待谓词**：队列等“有项”，事件组等“掩码成立”，流缓冲等“水位到达”。谓词不同，决定了阻塞表能不能排序、能否复用 TCB 字段、以及 ISR 能否直接唤醒。

### 5.4 协程 `croutine.c`（历史遗留）

默认关闭（`configUSE_CO_ROUTINES` 默认 0，`FreeRTOS.h:214-215`）。它与任务调度器是**两套并行机制**：自己维护就绪/延时/挂起链表（`croutine.c:44-56`），由 `vCoRoutineSchedule()` 驱动，协作式（不抢占）。**官方已建议不使用**，新项目应忽略此模块。

---

## 六、移植层 `portable/`

### 6.1 组织规律：编译器 × 架构

159 个 `port.c`、174 个 `portmacro.h`。一级按编译器厂商（GCC/RVDS/IAR/CCS/…），二级按架构（ARM_CM0/CM3/CM4F/CM7/CM23/CM33/CM55/CM85…）。

**关键事实：目录数远大于实际代码数**：
- `portable/Keil/See-also-the-RVDS-directory.txt` 与 `portable/ARMClang/Use-the-GCC-ports.txt` 是**纯指针文件**——Keil 复用 RVDS、ARMClang 复用 GCC。
- ARMv8-M 系列存在**主副本机制**：`portable/ARMv8M/non_secure/ReadMe.txt` 明写"不要使用这里的文件"；`portable/ARMv8M/copy_files.py:35-37` 的列表 + `185-192` 循环把主副本复制到 GCC/IAR 的各架构目录。**已实测验证**：`ARMv8M/non_secure/port.c` 与 `GCC/ARM_CM33/non_secure/port.c`、`IAR/ARM_CM55/non_secure/port.c` 的 md5 **完全相同**（`4e8bec8a8aeae4fca3cca63af3f6e992`）。
  **实践含义**：改 ARMv8-M 移植层应修改主副本并重跑 `copy_files.py`，否则会被覆盖。

### 6.2 上下文切换：为什么是 PendSV

`portable/GCC/ARM_CM4F/port.c:504` 起：

```asm
mrs r0, psp                     ; 取任务栈指针
tst r14, #0x10                  ; 判断是否使用了 FPU（扩展帧）
vstmdbeq r0!, {s16-s31}         ; 用了才补存浮点寄存器
stmdb r0!, {r4-r11, r14}        ; 存软件帧（含 EXC_RETURN 与临界嵌套）
str r0, [r2]                    ; 回写 TCB->pxTopOfStack
...
bl vTaskSwitchContext
```

**为何用 PendSV 而非在 SysTick 里直接切换**：`port.c:65-67` 把 PendSV 与 SysTick 都设为**最低优先级 255**（`port.c:429-431` 注释 "Make PendSV and SysTick the lowest priority interrupts"）。PendSV 可由软件挂起（写 ICSR 的 `PENDSVSET`，`portmacro.h:91`），最低优先级保证切换**在所有 ISR 之后经尾链执行**，不会打断任何中断；而 SysTick 还要做 tick 记账，直接在其中切换会拉长 tick ISR 且无法排序。

### 6.3 临界区：BASEPRI 的精确屏蔽

`portmacro.h:223` 用 `BASEPRI = configMAX_SYSCALL_INTERRUPT_PRIORITY`。它只屏蔽优先级**低于或等于**该值的中断，比它更高的硬实时中断获得**零延迟**。这正是 FreeRTOS 允许"高优先级中断不受内核影响"的机制。

### 6.4 第一个任务如何启动：伪造一次异常返回

`prvPortStartFirstTask`（`port.c:278`）：经 VTOR（`0xE000ED08`）读向量表首项得到初始 MSP 并复位主栈（`285-288`），清 FPCA（`289-290`），然后 `svc 0`。SVC 落到 `vPortSVCHandler`（`port.c:260`）：把 TCB 里预置的软件帧用 `ldmia` 弹出、把栈顶写入 PSP、`bx r14` —— **看起来就像一次正常的异常返回**，硬件随后按 PSP 自动弹出 `r0-r3,r12,lr,pc,xPSR`。这个"伪造栈帧"由 `pxPortInitialiseStack` 事先构造。

### 6.5 浮点：惰性叠加（lazy stacking）

CM4F 无条件开启 FPU（`port.c:445` 调 `vPortEnableVFP`，`port.c:834` 置 CPACR），并设置 FPCCR 的 `ASPEN|LSPEN`（`port.c:88-89,448`）。硬件按 `EXC_RETURN[4]` 自动压 `s0-s15`/`s16-s31` 扩展帧，软件只在 bit4=0 时补存 `s16-s31`（`port.c:516-518`）——**没用 FPU 的任务不付浮点保存代价**。

ARMv8-M 则用 `configENABLE_FPU`/`configENABLE_MPU` 条件编译（`portable/ARMv8M/non_secure/port.c:419-425,926,1033-1034`）。

### 6.6 TrustZone 的分裂结构

`ARM_CM33/55/85` 等目录分 `non_secure/` 与 `secure/`。非安全侧 `portasm.c` 的 PendSV 会先看 `EXC_RETURN[6]` 判断硬件帧落在安全栈还是非安全栈（`portable/GCC/ARM_CM33/non_secure/portasm.c:305-306`），并额外保存 `xSecureContext`/`PSPLIM`/`CONTROL`（`326-327`）。安全世界拥有**第二套上下文与堆**（`ARMv8M/secure/context/secure_context.c`）。

---

## 七、内存管理 `portable/MemMang/`

| 实现 | 算法 | 复杂度/碎片 | 适用场景 |
|---|---|---|---|
| `heap_1` | `xNextFreeByte` 线性推进（`heap_1.c:118-124`）；`vPortFree` 只断言（`143-149`） | O(1)，**零碎片但不可回收** | 启动期就把所有对象创建完的系统（最省代码、最可预测） |
| `heap_2` | 按块大小排序空闲链表、首次适配；插入只排序**不合并**（`heap_2.c:135-152`） | O(n)，碎片化 | **已被 heap_4 取代，勿用于新设计** |
| `heap_3` | 包装 libc 的 `malloc/free`，用 `vTaskSuspendAll` 保证线程安全（`heap_3.c:59-70,83-95`） | 取决于 libc | 已有成熟 libc 堆、或需要与外部代码共享堆 |
| `heap_4` | 地址序空闲链表，插入时**合并相邻空闲块**（`heap_4.c:504-560`），剩余大于 `heapMINIMUM_BLOCK_SIZE` 则分裂（`277-293`） | 首次适配 O(n)，碎片可控 | **通用首选** |
| `heap_5` | heap_4 算法 + `vPortDefineHeapRegions`（`heap_5.c:560`）支持多块不连续内存 | 同 heap_4 | 片上 SRAM + 外部 SDRAM 组合 |

**功耗视角**：堆算法本身不耗电，但**动态分配失败会导致任务创建失败或运行异常**；且 `heap_4/heap_5` 的 O(n) 搜索耗时随碎片增长。低功耗设备常见做法是用 `heap_1` 或静态分配（`configSUPPORT_STATIC_ALLOCATION`）把内存行为完全确定化，减少运行期不确定性。

---

## 八、⚡ 功耗专题（重点）

> 本章是全文重点。FreeRTOS 的低功耗能力**不是某一个功能**，而是一条从"空闲任务"贯穿到"移植层汇编"的**决策链**。

### 8.1 功耗决策链全景

```
空闲任务 prvIdleTask (tasks.c:5908)
   │
   ├─① 能睡多久？ prvGetExpectedIdleTime()        (tasks.c:3998)
   │      否决条件 1/2/3 → 返回 0（不睡）
   │      否则 = xNextTaskUnblockTime - xTickCount
   │
   ├─② 超过阈值才睡：xExpectedIdleTime >= configEXPECTED_IDLE_TIME_BEFORE_SLEEP (默认 2)
   │
   ├─  vTaskSuspendAll()  （冻结调度，准备入睡）
   │
   ├─③ 睡得安全吗？ eTaskConfirmSleepModeStatus()  (tasks.c:6045)
   │      三种情况 → eAbortSleep（放弃睡眠）
   │      全任务无限阻塞 → eNoTasksWaitingTimeout（可深睡）
   │      否则 → eStandardSleep
   │
   ├─④ 真的睡下去： portSUPPRESS_TICKS_AND_SLEEP()
   │      → vPortSuppressTicksAndSleep() (port.c，各 port 实现)
   │        重编程 SysTick → configPRE_SLEEP_PROCESSING → WFI → configPOST_SLEEP_PROCESSING
   │
   └─⑤ 醒来补账： vTaskStepTick( ulCompleteTickPeriods )  (tasks.c:4665)
          （不调用 tick hook！）
```

### 8.2 ① `prvGetExpectedIdleTime()`：四个否决条件

`tasks.c:3998-4055`。返回值语义是"预期可空闲的 tick 数"，**返回 0 表示不该睡**：

| 条件 | 代码位置 | 含义 |
|---|---|---|
| `pxCurrentTCB->uxPriority > tskIDLE_PRIORITY` | `tasks.c:4030` | 当前运行的不是空闲任务 |
| 空闲优先级就绪表长度 > 1（SMP 下 > `configNUMBER_OF_CORES`） | `tasks.c:4034`、`tasks.c:5959` | **还有别的空闲优先级任务就绪**，下一 tick 就会切换 |
| `xHigherPriorityReadyTasks != pdFALSE` | `tasks.c:4040` | 仅在 `configUSE_PREEMPTION == 0` 时可能：协作式下高优先级任务可能已就绪 |
| 否则 `xReturn = xNextTaskUnblockTime - xTickCount` | `tasks.c:4046-4048` | **睡眠上限 = 下一个任务唤醒时刻** |

> **核心洞察**：`xNextTaskUnblockTime` 是**全系统最近的唤醒事件**（任何延时、任何带超时的阻塞、软件定时器守护任务的下次到期）。它把"能睡多久"统一归结为一个变量。**任何让某个任务频繁定时唤醒的应用，都在直接压缩睡眠时长。**

### 8.3 ② `configEXPECTED_IDLE_TIME_BEFORE_SLEEP`：最小睡眠阈值

```c
#ifndef configEXPECTED_IDLE_TIME_BEFORE_SLEEP
    #define configEXPECTED_IDLE_TIME_BEFORE_SLEEP    2      /* FreeRTOS.h:2731-2732 */
#endif
#if configEXPECTED_IDLE_TIME_BEFORE_SLEEP < 2
    #error configEXPECTED_IDLE_TIME_BEFORE_SLEEP must not be less than 2   /* FreeRTOS.h:2735-2736 */
#endif
```

**为什么不能小于 2**：进入/退出睡眠本身有开销（重编程 SysTick、DSB/ISB、补偿计算）。只睡 1 个 tick 得不偿失，且 ARM 移植层的算法天然要求 `xExpectedIdleTime >= 2`（`port.c:645` 注释 "The expected idle time is always at least two ticks"）。

空闲任务中做了**两次采样**（`tasks.c:5988` 和 `6006`）：第一次不加锁（廉价试探，结果可能已过时），第二次在 `vTaskSuspendAll()` 之后（权威值）。注释明确解释了原因：不希望每次空闲迭代都做 挂起/恢复调度器的开销（`tasks.c:5981-5987`）。

### 8.4 ③ `eTaskConfirmSleepModeStatus()`：三种"放弃睡眠"

`tasks.c:6045-6092`：

| 条件 | 返回 | 物理含义 |
|---|---|---|
| `xPendingReadyList` 非空 | `eAbortSleep` | 调度器挂起期间有任务被唤醒 |
| `xYieldPendings[core] != pdFALSE` | `eAbortSleep` | 挂起期间产生了切换请求 |
| `xPendedTicks != 0` | `eAbortSleep` | **tick 已经发生但被挂起**，必须立刻处理 |
| 全部任务都在 `xSuspendedTaskList`（即无限阻塞） | `eNoTasksWaitingTimeout` | 没有任何定时唤醒源 → **可以关闭所有时钟** |
| 其它 | `eStandardSleep` | 正常浅睡，靠 SysTick 唤醒 |

注意注释（`tasks.c:6087-6089`）："If all the tasks are in the suspended list (**which might mean they have an infinite block time rather than actually being suspended**) then it is safe to turn all clocks off"。也就是说 `vTaskDelay(portMAX_DELAY)` 也算"无限期等待"。

### 8.5 ④ 两种睡眠深度 —— 以及一个重要的移植层差异

**`eStandardSleep`**：重编程 SysTick 到 `xExpectedIdleTime` 后执行 `WFI`。SysTick 到期即唤醒。
**`eNoTasksWaitingTimeout`**：连 SysTick 都可以关闭，只等外部中断。

**实测结论（本仓库全量 grep）**：`eNoTasksWaitingTimeout` 这个返回值**只有 5 个移植实现真正处理**：

```
portable/GCC/RX100/port.c
portable/IAR/RX100/port.c
portable/Renesas/RX100/port.c
portable/ThirdParty/Partner-Supported-Ports/GCC/AVR_AVRDx/port.c
portable/ThirdParty/Partner-Supported-Ports/GCC/AVR_Mega0/port.c
```

**全部 ARM Cortex-M 移植（ARM_CM0/CM3/CM4F/CM7/CM23/CM33/CM55/CM85 及 ARMv8M 主副本）都只判断 `eAbortSleep`**，例如 `portable/GCC/ARM_CM4F/port.c:604`：

```c
if( eTaskConfirmSleepModeStatus() == eAbortSleep )
{
    __asm volatile ( "cpsie i" ::: "memory" );   /* 放弃睡眠，恢复中断 */
}
else
{
    /* ... 一律重编程 SysTick 浅睡 ... */
```

**这是设计使然，不是缺陷**：Cortex-M 的 tickless 实现**依赖 SysTick 作为唤醒源**，而 `eNoTasksWaitingTimeout` 要求关掉所有时钟——把 SysTick 关掉就没有唤醒源了，除非应用自己配置 RTC/LPTIM/WKUP 引脚。

> **实践建议**：若在 Cortex-M 上需要"无期限深睡"，不能只设 `configUSE_TICKLESS_IDLE=1`。正确做法是在 `configPRE_SLEEP_PROCESSING(x)` 中自行配置 RTC/低功耗定时器并关停 SysTick，把参数置 0（告诉移植层"不要执行 WFI，我自己处理"），醒来后在 `configPOST_SLEEP_PROCESSING` 中调用 `xTaskCatchUpTicks()`（`tasks.c:4707`）补齐丢失的 tick。`port.c:665-670` 的注释明确支持这种用法：
> *"configPRE_SLEEP_PROCESSING() can set its parameter to 0 to indicate that its implementation contains its own wait for interrupt or wait for event instruction, and so wfi should not be executed again."*

### 8.6 ARM_CM4F 的完整睡眠流程（`portable/GCC/ARM_CM4F/port.c:580-810`）

```
 1. cpsid i                      ← 注意：不用 taskENTER_CRITICAL，因为要保留"任意中断都能唤醒"的能力
 2. eTaskConfirmSleepModeStatus() == eAbortSleep ? → cpsie i 返回
 3. 停 SysTick（只保留 CLK|INT 位，清除 ENABLE）
 4. 读 SYST_CVR 得剩余计数 ulSysTickDecrementsLeft（为 0 时按一个整周期算）
 5. ulReloadValue = 剩余 + ulTimerCountsForOneTick * (xExpectedIdleTime - 1)
 6. 若 SysTick 中断已 pending → 清除并 ulReloadValue -= 一个 tick 周期
 7. ulReloadValue -= ulStoppedTimerCompensation     ← 停止时钟期间的补偿
 8. 写 SYST_RVR、清 SYST_CVR、重新使能 SysTick
 9. configPRE_SLEEP_PROCESSING( xModifiableIdleTime )   ← 用户钩子 1
10. if( xModifiableIdleTime > 0 ) { dsb; wfi; isb; }    ← 真正的睡眠点
11. configPOST_SLEEP_PROCESSING( xExpectedIdleTime )    ← 用户钩子 2
12. cpsie i                     ← 让唤醒中断立刻执行（而不是等退出后再执行）
13. cpsid i；停 SysTick；读 COUNTFLAG 判断唤醒来源：
      是 tick 唤醒 → ulCompleteTickPeriods = xExpectedIdleTime - 1
      其它中断唤醒 → 从 SYST_CVR 反算实际睡眠时长，四舍五入到整 tick
14. 恢复 SYST_RVR 为标准值、重启 SysTick
15. vTaskStepTick( ulCompleteTickPeriods )              ← 补 tick 计数
16. cpsie i
```

### 8.7 量化：单次睡眠的**硬上限**是多少？

移植层在 `vPortSetupTimerInterrupt()`（`port.c:813-822`）中预计算：

```c
ulTimerCountsForOneTick = ( configSYSTICK_CLOCK_HZ / configTICK_RATE_HZ );   /* port.c:817 */
xMaximumPossibleSuppressedTicks = portMAX_24_BIT_NUMBER / ulTimerCountsForOneTick;  /* port.c:818 */
ulStoppedTimerCompensation = portMISSED_COUNTS_FACTOR / ( configCPU_CLOCK_HZ / configSYSTICK_CLOCK_HZ );  /* port.c:819 */
```

关键：**SysTick 是 24 位计数器**（`portMAX_24_BIT_NUMBER` = 0xFFFFFF = 16,777,215）。

$$\text{单次最长睡眠时间} = \frac{2^{24}}{\text{configSYSTICK\_CLOCK\_HZ}} \text{ 秒}$$

**这个上限与 `configTICK_RATE_HZ` 无关**，只由 SysTick 时钟频率决定：

| SysTick 时钟 | 单次睡眠硬上限 |
|---|---|
| 16 MHz | ≈ 1.05 s |
| 100 MHz | ≈ 168 ms |
| 168 MHz | ≈ 100 ms |

**实践含义**：即使没有任何任务需要唤醒，Cortex-M 上单次睡眠也不会超过约 100 ms（典型 168 MHz 配置）。要突破这个上限，必须改用 RTC/LPTIM 作为唤醒源（即 8.5 节的深睡方案）。

`ulStoppedTimerCompensation` 补偿的是"停止/启动时钟过程中的计数损失"，其因子 `portMISSED_COUNTS_FACTOR = 94`（`port.c:105`）是经验值——**这也是 tickless 模式存在微小时间漂移的原因**，`port.c:611-614` 注释坦承："using the tickless mode will inevitably result in some tiny drift of the time maintained by the kernel with respect to calendar time"。

### 8.8 ⑤ `vTaskStepTick()` 的边界与陷阱

`tasks.c:4665-4700`：

```c
xUpdatedTickCount = xTickCount + xTicksToJump;
configASSERT( xUpdatedTickCount <= xNextTaskUnblockTime );   /* tasks.c:4678 */

if( xUpdatedTickCount == xNextTaskUnblockTime )              /* tasks.c:4681 */
{
    taskENTER_CRITICAL();
    { xPendedTicks++; }                                      /* tasks.c:4690 */
    taskEXIT_CRITICAL();
    xTicksToJump--;                                          /* tasks.c:4693 */
}
xTickCount += xTicksToJump;                                  /* tasks.c:4699 */
```

两个要点：

1. **临界区保护**：虽然调度器已挂起（`uxSchedulerSuspended != 0` 有断言），但 **tick 中断仍可能修改 `xPendedTicks`**，故必须短临界区（`tasks.c:4684-4691`）。
2. **`xTicksToJump--` 的动机**：若刚好走到 `xNextTaskUnblockTime`，就刻意**少走一个 tick**并把该 tick 记为 pending，交给 `xTaskIncrementTick()` 在调度器恢复后处理——这样延时任务能被**正确地**唤醒，而不是被跳过。

⚠ **重要陷阱（`tasks.c:4674-4675` 注释明确说明）**：

```c
/* ... Note this does *not* call the tick hook function for each stepped tick. */
```

**`vTaskStepTick` 不会为被"跳过"的 tick 调用 `vTaskApplicationTickHook()`。** 任何依赖 tick hook 做计数/看门狗/时间基准的应用，在启用 tickless 后都会漏计数。这是 tickless 最容易被忽视的副作用。

**`xTaskCatchUpTicks()`**（`tasks.c:4707`）是补救工具：内部用 `vTaskSuspendAll()` + `xPendedTicks += xTicksToCatchUp` + `xTaskResumeAll()`，**模拟"调度器挂起期间发生了 n 次 tick"**，从而走完整 tick 处理路径（含 hook 之外的唤醒逻辑），适用于用户自实现深睡后补账。

### 8.9 tickless 牵动的其它内核代码（易漏）

启用 `configUSE_TICKLESS_IDLE` 后，内核在 **6 处**额外调用 `prvResetNextTaskUnblockTime()`：

| 位置 | 场景 |
|---|---|
| `tasks.c:5532` | `xTaskRemoveFromEventList`（队列/信号量唤醒） |
| `tasks.c:5626` | `vTaskRemoveFromUnorderedEventList`（事件组唤醒） |
| `tasks.c:8108` | `xTaskNotify`（任务通知） |
| `tasks.c:8252` / `tasks.c:8386` | 任务通知的中断安全版本 |
| `tasks.c:6621` | `prvResetNextTaskUnblockTime` 自身实现 |

**原因**（`tasks.c:5534-5541` 注释）：`xNextTaskUnblockTime` 通常只在 tick 到达时才更新。但任务**因非超时原因**（事件/通知）被唤醒后，如果它原本的阻塞超时时刻就是 `xNextTaskUnblockTime`，那么不重算的话，内核会**多睡一段本可以睡的时间**（或反之）。tickless 下"尽早入睡"的价值更高，所以必须立刻重算。

### 8.10 配置项对功耗的影响矩阵

| 配置项 | 默认值 | 对功耗的影响 |
|---|---|---|
| `configUSE_TICKLESS_IDLE` | `0`（`FreeRTOS.h:2739-2740`） | **总开关**。`0`=每 tick 必醒；`1`=用移植层通用实现；`>1`=用户自定义 `portSUPPRESS_TICKS_AND_SLEEP`（`FreeRTOS.h:2727-2728` 提供空宏默认） |
| `configTICK_RATE_HZ` | 惯例 1000 | **最直接的功耗旋钮**。每秒唤醒次数 = tick 频率。1000 Hz → 100 Hz 可减少 90% 的 tick 中断次数（代价：时间粒度变粗 10 倍，`vTaskDelay` 精度下降） |
| `configEXPECTED_IDLE_TIME_BEFORE_SLEEP` | `2` | 抬高它可避免"短睡"的进出开销，但会浪费本可睡眠的短空闲期 |
| `configUSE_IDLE_HOOK` | `0`（必填） | `=1` 时在空闲任务里执行用户代码（传统低功耗做法是插 `WFI`）。**注意**：与 tickless 同时使用会互相干扰——tickless 已内建 WFI |
| `configUSE_PASSIVE_IDLE_HOOK` | `0`（SMP 下必填，`FreeRTOS.h:198-200,525-527`） | SMP 下关闭空闲核的官方钩子（详见 8.11） |
| `configUSE_PREEMPTION` | `1`（必填） | `=0`（协作式）会让 `prvGetExpectedIdleTime` 多一个否决条件（`tasks.c:4040`） |
| `configIDLE_SHOULD_YIELD` | `1` | `=1` 时同优先级任务会让出 CPU，把空闲时间切碎，不利于统计真实空闲率 |
| `configUSE_TIME_SLICING` | `1` | 同优先级时间片轮转，增加切换与唤醒次数 |
| `configUSE_TICK_HOOK` | `0` | 启用后每次 tick 回调。**tickless 的 step tick 不会调用它**（见 8.8） |
| `configGENERATE_RUN_TIME_STATS` | `0` | **高功耗代价**：需要一个远高于 tick 频率的独立定时器（通常 10~100 倍），并需实现 `portCONFIGURE_TIMER_FOR_RUN_TIME_STATS`/`portGET_RUN_TIME_COUNTER_VALUE`（`FreeRTOS.h` 有强制校验）。仅调试期开启 |
| `configUSE_TIMERS` + 定时器周期 | 依应用 | **最近的软件定时器到期时刻会直接成为睡眠上限**（见 5.1） |
| `configUSE_TRACE_FACILITY` | `0` | V11 新增 `traceENTER_xxx`/`traceRETURN_xxx` 钩子（全仓库 **199 个调用点**：tasks.c 96、queue.c 45、stream_buffer.c 23、timers.c 20、event_groups.c 15）。**默认展开为空宏，零开销**；一旦重定义即为每次 API 调用的额外成本 |

### 8.11 SMP（多核）下的功耗路径

V11 的 SMP **不是**通过 tickless 实现的，而是走**空闲核关闭**路径：

- 每个核都有空闲任务：core 0 是 `prvIdleTask`，其余是 `prvPassiveIdleTask`（`tasks.c:5837`，创建逻辑见 `tasks.c:3617-3635`，注释明言 "configNUMBER_OF_CORES - 1 passive idle tasks are also created"）。
- 官方钩子 `vApplicationPassiveIdleHook()` 在**每个空闲核**上被调用（`tasks.c:6017-6028`），注释直述其用途：

  > *"This hook is intended to manage core activity such as **disabling cores that go idle**."*

  并附强制约束：`vApplicationPassiveIdleHook() MUST NOT, UNDER ANY CIRCUMSTANCES, CALL A FUNCTION THAT MIGHT BLOCK.`
- `prvGetExpectedIdleTime` 在 SMP 下把阈值从 `> 1` 改为 `> configNUMBER_OF_CORES`（`tasks.c:5959`），即"所有核的空闲任务都在跑"才算真空闲。
- **注意**：`vPortSuppressTicksAndSleep` 会停掉 SysTick——在 SMP 下这会**影响所有核**，而移植层没有跨核协调代码。因此多核场景下正确做法是**不启用 tickless**，用 `configUSE_PASSIVE_IDLE_HOOK` 关闭空闲核。

### 8.12 中断唤醒机制与注意事项

- 睡眠点前的 `cpsid i`（`port.c:602`）**关闭的是全部中断**（PRIMASK），而非 `BASEPRI` 的精确屏蔽。移植层注释解释了原因（`port.c:600-601`）：*"Enter a critical section but don't use the taskENTER_CRITICAL() method as that will mask interrupts that should exit sleep mode."* —— **任何被 BASEPRI 屏蔽的中断都必须能唤醒 CPU**，否则会睡过头。
- `WFI` 会被**任意**使能的中断唤醒（无论是否有 ISR 注册）。因此持续的、与业务无关的中断（如未清理的 DMA/比较器标志）会让 CPU 反复醒来，**让 tickless 完全失效**。
- `configPRE_SLEEP_PROCESSING` 把参数置 0 可完全接管睡眠（用于 WFE、或自行关时钟）。
- 可选 `configPRE_SUPPRESS_TICKS_AND_SLEEP_PROCESSING`（`FreeRTOS.h:2747-2748` 提供空宏）在**更早**的位置决策是否放弃睡眠（`tasks.c:6004`），适合"按运行状态动态禁睡"的场景。

### 8.13 tickless 失效的常见原因（排查清单）

按出现频率排序：

1. **高频软件定时器**：如 1 ms 周期的 `xTimerStart`，守护任务每次都定时阻塞，睡眠上限被压到 1 tick → 等于没有 tickless。
2. **任何任务用 `vTaskDelay(1)` 轮询**：直接把 `xNextTaskUnblockTime` 拉到下一个 tick。
3. **未启用 `configUSE_TICKLESS_IDLE`**（默认就是 0，很容易忘）。
4. **中断持续触发**：WFI 被无关中断唤醒（8.12）。
5. **tick 频率过高**：`configTICK_RATE_HZ = 1000` 时每秒至少醒 1000 次。
6. **期望 Cortex-M 深睡但移植层不支持**：`eNoTasksWaitingTimeout` 未被处理（8.5），必须自行接管（RTC/LPTIM）。
7. **`configPRE_SLEEP_PROCESSING` 未正确配置外设**：睡眠前没关外设时钟/没切到低功耗稳压器，睡了但没省电。
8. **依赖 tick hook 计时**：tickless 下 step tick 不触发 hook（8.8），会导致逻辑错误而非功耗问题——但常被误判为"功耗异常"。
9. **调试器/仿真器连接**：会阻止处理器进入低功耗状态（常见误判）。

### 8.14 功耗优化推荐配置（Cortex-M，参考起点）

```c
#define configUSE_TICKLESS_IDLE                 1     /* 开启通用 tickless */
#define configTICK_RATE_HZ                      100   /* 先降节拍：立竿见影 */
#define configEXPECTED_IDLE_TIME_BEFORE_SLEEP   2     /* 保持最小，避免破坏短空闲 */
#define configUSE_IDLE_HOOK                     0     /* 不要与 tickless 竞争 */
#define configIDLE_SHOULD_YIELD                 0     /* 减少空闲时间被切碎 */
#define configUSE_TIME_SLICING                  0     /* 非必需时关闭时间片 */
#define configGENERATE_RUN_TIME_STATS           0     /* 调试完必须关 */
#define configUSE_TICK_HOOK                     0     /* 或确认不依赖它计时 */

/* 可选：睡眠前后管理外设时钟 / 切换稳压器 */
#define configPRE_SLEEP_PROCESSING( x )    /* 关外设时钟、切 LDO */
#define configPOST_SLEEP_PROCESSING( x )   /* 恢复 */

/* 可选：按应用状态动态禁睡 */
#define configPRE_SUPPRESS_TICKS_AND_SLEEP_PROCESSING( x )   /* 置 x=0 可放弃本 次睡眠 */
```

再配合：把软件定时器周期拉长或改用硬件定时器 + 中断；确保所有中断标志被正确清除。

---

## 九、配置体系与裁剪

`include/FreeRTOS.h` 含 **50 处 `#error` 校验**，构成一道"配置正确性防线"。典型校验：

- **必填项**（缺失即编译失败）：`configUSE_PREEMPTION`、`configUSE_IDLE_HOOK`、`configMAX_PRIORITIES`、`configMINIMAL_STACK_SIZE`、`configTICK_TYPE_WIDTH_IN_BITS`（或旧 `configUSE_16_BIT_TICKS`，二者只能定义其一）。
- **互斥约束**：`configUSE_STATS_FORMATTING_FUNCTIONS` 依赖动态分配；`INCLUDE_vTaskDelayUntil` 与 `INCLUDE_xTaskDelayUntil` 不可同时定义。
- **SMP 专属要求**（`configNUMBER_OF_CORES > 1` 时）：必须定义 `portGET_CORE_ID`、`portYIELD_CORE`、`configUSE_PASSIVE_IDLE_HOOK`、`portENTER_CRITICAL_FROM_ISR`、`portCLEAR_INTERRUPT_MASK_FROM_ISR`，且 `configUSE_PORT_OPTIMISED_TASK_SELECTION` 被禁用、`configUSE_CORE_AFFINITY` 才可用。
- **一致性检查**：`configUSE_MUTEXES` 未开则递归互斥量不可用；`configUSE_TASK_PREEMPTION_DISABLE` 需 `configUSE_PREEMPTION == 1` 且 `configRUN_MULTIPLE_PRIORITIES == 1`。

**设计意图**：把尽可能多的配置错误从"运行时玄学崩溃"前移到**编译期**。这也解释了 `FreeRTOS.h` 高达 3371 行的原因——它绝大部分是默认值与校验，而非代码。

---

## 十、结论与学习路径

### 10.1 三个贯穿全内核的设计思想

1. **用最小的原语组合出全部功能**：一条链表（`list.c`）+ 一个队列（`queue.c`）→ 任务状态机、信号量、互斥量、队列集、软件定时器、消息缓冲。理解这两个文件就读懂了内核的 80%。
2. **把"排序键"用足**：任务在事件表里的键值是 `MAX_PRIORITIES - priority`（降序），在延时表里是唤醒时刻（升序）。同一套 `vListInsert` 因此同时服务于"优先级调度"和"时间调度"。
3. **用结构约束换运行速度**：`pxTopOfStack` 必须在 TCB 首部（切换只需一个指针）、末尾哨兵项（免判空）、`pxContainer` 反向指回（O(1) 移除）、惰性浮点保存（不用的任务不付费）。

### 10.2 建议的阅读顺序

```
list.c / list.h                    ← 地基，30 分钟
  └─ tasks.c: TCB → 就绪表 → 双延时表 → vTaskSwitchContext → xTaskIncrementTick
       └─ queue.c: Queue_t → 双等待表 → 信号量退化 → prvLockQueue/prvUnlockQueue
            └─ timers.c / event_groups.c / stream_buffer.c   ← 三种不同的同步范式
                 └─ portable/GCC/ARM_CM4F/port.c             ← 汇编与硬件衔接
                      └─ portable/MemMang/heap_4.c           ← 内存管理
```

### 10.3 关于功耗，最需要记住的五句话

1. **`xNextTaskUnblockTime` 就是睡眠时长的天花板**——所有提高唤醒频率的行为（短延时轮询、高频定时器、高节拍）都会立刻反映在功耗上。
2. **`configTICK_RATE_HZ` 是最省力的功耗旋钮**，但要在时间精度与功耗之间权衡。
3. **Cortex-M 的 tickless 单次睡眠有约 100 ms 硬件上限**（SysTick 24 位），要更长必须换 RTC/LPTIM 唤醒源。
4. **`vTaskStepTick` 不调用 tick hook**——这是 tickless 最隐蔽的语义变化。
5. **多核（SMP）不要用 tickless**，用 `configUSE_PASSIVE_IDLE_HOOK` 关空闲核。

---

*报告完。全部结论均基于本仓库 V11.3.1 源码实际阅读；关键论断（PendSV 优先级、ARMv8M 主副本 md5 一致性、TCB 布局、优先级缓存宏、`eNoTasksWaitingTimeout` 支持列表、trace 钩子数量）已逐项抽查验证。*
