# Research 流式输出方案

## ✅ 已实现的流式事件

### 搜索相关事件 (用户要求的"搜索到了哪些内容")

1. **开始搜索** - `supervisor_tools`
   ```json
   {"type":"status","stage":"searching","topic":"主题A"}
   ```

2. **搜索结果** - `supervisor_tools` (每个主题完成时)  
   ```json
   {"type":"search_result","topic":"主题A","snippet":"压缩后的研究摘要(400字内)"}
   ```

3. **搜索命中** - `researcher_tools` (每次搜索工具返回时)
   ```json
   {"type":"search_hit","source":"tavily_search","topic":"主题A","snippet":"原始搜索结果(300字内)"}
   ```

### 整合相关事件 (用户要求的"正在执行之类的")

4. **正在压缩整合** - `compress_research`
   ```json
   {"type":"status","stage":"compressing","topic":"主题A"}  
   ```

5. **正在生成报告** - `final_report_generation`
   ```json
   {"type":"status","stage":"generating_report"}
   ```

## 技术实现

### 修改的文件
- `deep_researcher.py`: 添加 `_stream_emit()` 和 `get_stream_writer()` 支持
- 所有相关节点都添加了对应的流式事件发送

### 使用方法
```python
# 调用时使用 stream_mode=["updates","custom"]
async for mode, chunk in deep_researcher.astream(
    research_input, 
    research_config, 
    stream_mode=["updates","custom"]
):
    if mode == "custom":
        # chunk 是我们的事件，直接使用
        print(f"[{chunk['type']}] {chunk.get('stage', '')}: {chunk.get('topic', '')}")
    elif mode == "updates":  
        # 处理节点级状态更新
        pass
```

### 事件时序
用户将看到如下时序的事件流：

1. `searching` - 开始搜索各个主题
2. `search_hit` - 每次搜索工具返回结果  
3. `search_result` - 每个主题搜索完成
4. `compressing` - 开始整合压缩每个主题
5. `generating_report` - 开始生成最终报告
6. `report` - 最终报告内容

这样用户就能实时看到"搜索到了哪些内容"以及"正在执行"的进度提示。