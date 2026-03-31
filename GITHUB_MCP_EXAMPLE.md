# GitHub MCP 工具使用示例

这个文档展示了如何使用 Model Context Protocol (MCP) 的 GitHub 工具来完成各种任务。

## 🎯 演示内容

### 1. 搜索仓库 (search_repositories)

使用 `mcp_github_search_repositories` 搜索感兴趣的开源项目。

**示例查询：**
```javascript
{
  "query": "typescript vue awesome",
  "perPage": 5
}
```

**搜索结果：**
- 找到了 72 个相关仓库
- 包括 awesome-frontendmasters, vue-smooth-picker 等项目

### 2. 获取文件内容 (get_file_contents)

使用 `mcp_github_get_file_contents` 查看仓库的文件结构和代码。

**示例：**
```javascript
{
  "owner": "hiyali",
  "repo": "vue-smooth-picker",
  "path": "."
}
```

**获取到的内容：**
- .gitignore
- LICENSE
- README.md
- package.json
- src/ (目录)
- tsconfig.json
- vite.config.ts

### 3. 创建 Issue (create_issue)

使用 `mcp_github_create_issue` 为项目创建问题或功能请求。

**示例：**
```javascript
{
  "owner": "hiyali",
  "repo": "vue-smooth-picker",
  "title": "【示例】GitHub API 使用演示",
  "body": "这是一个使用 GitHub API 创建的示例 issue..."
}
```

**结果：**
- ✅ 成功创建了 Issue #65
- URL: https://github.com/hiyali/vue-smooth-picker/issues/65

### 4. 搜索代码 (search_code)

使用 `mcp_github_search_code` 在 GitHub 上搜索特定代码。

**示例查询：**
```javascript
{
  "q": "vue composition API typescript",
  "per_page": 3
}
```

**搜索结果：**
- 找到 40,320 个匹配项
- 返回了相关的代码文件和文档

## 🛠️ 可用的 GitHub 工具

| 工具名称 | 功能描述 |
|---------|---------|
| `search_repositories` | 搜索 GitHub 仓库 |
| `get_file_contents` | 获取仓库文件或目录内容 |
| `create_issue` | 创建新的 Issue |
| `update_issue` | 更新现有 Issue |
| `list_issues` | 列出仓库的 Issues |
| `create_pull_request` | 创建 Pull Request |
| `list_pull_requests` | 列出 Pull Requests |
| `get_pull_request` | 获取 PR 详情 |
| `create_pull_request_review` | 审查 Pull Request |
| `merge_pull_request` | 合并 Pull Request |
| `search_code` | 搜索代码 |
| `search_issues` | 搜索 Issues |
| `search_users` | 搜索用户 |
| `create_repository` | 创建新仓库 |
| `fork_repository` | Fork 仓库 |
| `create_branch` | 创建新分支 |
| `push_files` | 推送文件到仓库 |
| `list_commits` | 查看提交历史 |
| `add_issue_comment` | 添加 Issue 评论 |

## 📝 使用场景

1. **项目管理**: 自动化创建和管理 Issues
2. **代码搜索**: 快速找到相关的开源项目和代码示例
3. **协作开发**: 创建 PR 和进行代码审查
4. **仓库管理**: 批量操作文件和配置
5. **数据分析**: 收集和分析 GitHub 上的项目数据

## 🔗 相关链接

- [MCP GitHub Server](https://github.com/modelcontextprotocol/servers)
- [GitHub API 文档](https://docs.github.com/en/rest)
- [示例 Issue #65](https://github.com/hiyali/vue-smooth-picker/issues/65)

---

*此文档由 AI 助手自动生成，用于演示 GitHub MCP 工具的使用。*

生成时间：2026-03-31
