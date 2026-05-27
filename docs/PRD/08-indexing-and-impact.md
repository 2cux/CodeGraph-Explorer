# 18. 代码索引逻辑

## 18.1 文件扫描

扫描 `.py` 文件。

忽略：

```text
.git
venv
.venv
node_modules
dist
build
__pycache__
.pytest_cache
.mypy_cache
```

---

## 18.2 提取实体

对每个 Python 文件提取：

1. file；
2. module；
3. class；
4. function；
5. method；
6. import；
7. test function；
8. docstring；
9. signature；
10. source location。

---

## 18.3 提取关系

提取：

1. file contains class/function；
2. class contains method；
3. file imports module；
4. function calls function；
5. method calls method；
6. class inherits class；
7. function references external symbol；
8. test potentially tests target function。

---

## 18.4 调用解析策略

优先级：

1. 同文件函数精确匹配；
2. import 后符号匹配；
3. class method 匹配；
4. self.method 匹配；
5. 类型注解辅助匹配；
6. attribute guess；
7. external symbol；
8. unresolved。

每条 calls 边必须带：

```text
confidence
resolution
source_location
```

---

# 19. Impact 分析逻辑

## 19.1 输入

```text
symbol_id
```

或 Context Pack 中的 target symbol。

---

## 19.2 输出

1. changed symbol；
2. upstream callers；
3. downstream callees；
4. affected symbols；
5. affected files；
6. related tests；
7. risk level；
8. risk reasons。

---

## 19.3 风险等级规则

risk level 可由以下因素决定：

1. callers 数量；
2. callees 数量；
3. 是否在 auth / payment / permission / delete 等敏感路径；
4. 是否有相关测试；
5. 是否跨模块；
6. 是否是公共 API；
7. 是否存在低置信度关系；
8. 是否被多个文件 import。
