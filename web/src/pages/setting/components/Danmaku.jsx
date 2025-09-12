import { useState, useEffect } from 'react'
import { Card, Form, Select, Button, message, Typography, Space, Alert, Divider, Modal, Progress, Table } from 'antd'
import { FolderOutlined, FileOutlined, InfoCircleOutlined, SyncOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { getDanmakuFilePathStyle, setDanmakuFilePathStyle, previewDanmakuMigration, executeDanmakuMigration } from '../../../apis'

const { Title, Text, Paragraph } = Typography
const { Option } = Select

export const Danmaku = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [initialLoading, setInitialLoading] = useState(true)
  const [migrationModalVisible, setMigrationModalVisible] = useState(false)
  const [migrationLoading, setMigrationLoading] = useState(false)
  const [migrationStats, setMigrationStats] = useState(null)

  // 加载当前配置
  useEffect(() => {
    const loadConfig = async () => {
      try {
        const response = await getDanmakuFilePathStyle()
        form.setFieldsValue({
          danmakuFilePathStyle: response.data?.value || 'emby'
        })
      } catch (error) {
        message.error('加载配置失败')
      } finally {
        setInitialLoading(false)
      }
    }
    loadConfig()
  }, [form])

  // 保存配置
  const handleSave = async (values) => {
    setLoading(true)
    try {
      await setDanmakuFilePathStyle({ value: values.danmakuFilePathStyle })
      message.success('弹幕设置已保存，重启服务后生效')
    } catch (error) {
      message.error('保存失败: ' + (error.response?.data?.detail || error.message))
    } finally {
      setLoading(false)
    }
  }

  // 预览迁移
  const previewMigration = async () => {
    setMigrationLoading(true)
    try {
      const response = await previewDanmakuMigration()
      setMigrationStats(response.data)
      setMigrationModalVisible(true)
    } catch (error) {
      message.error('预览迁移失败: ' + (error.response?.data?.detail || error.message))
    } finally {
      setMigrationLoading(false)
    }
  }

  // 执行迁移
  const executeMigration = async () => {
    setMigrationLoading(true)
    try {
      const response = await executeDanmakuMigration()
      setMigrationStats(response.data)
      message.success(`迁移完成！成功迁移 ${response.data.files_migrated} 个文件`)
    } catch (error) {
      message.error('执行迁移失败: ' + (error.response?.data?.detail || error.message))
    } finally {
      setMigrationLoading(false)
    }
  }

  const pathStyleExamples = {
    emby: [
      {
        type: '电视剧',
        path: '/danmaku/TV Shows/某科学的超电磁炮T (2020)/Season 3/S03E01_超电磁炮.xml',
        icon: <FolderOutlined style={{ color: '#1890ff' }} />
      },
      {
        type: '电影',
        path: '/danmaku/Movies/你的名字 (2016)/你的名字.xml',
        icon: <FileOutlined style={{ color: '#52c41a' }} />
      },
      {
        type: 'OVA',
        path: '/danmaku/OVA/某科学的超电磁炮 OVA (2019)/OVA01_特别篇.xml',
        icon: <FileOutlined style={{ color: '#faad14' }} />
      }
    ],
    simple: [
      {
        type: '所有类型',
        path: '/danmaku/196/25000196010001.xml',
        icon: <FileOutlined style={{ color: '#8c8c8c' }} />
      }
    ]
  }

  const currentStyle = Form.useWatch('danmakuFilePathStyle', form) || 'emby'

  if (initialLoading) {
    return <Card loading />
  }

  return (
    <Card>
      <Title level={4}>弹幕文件设置</Title>
      
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSave}
        initialValues={{ danmakuFilePathStyle: 'emby' }}
      >
        <Form.Item
          label="文件路径风格"
          name="danmakuFilePathStyle"
          tooltip="选择弹幕文件的存储路径和命名方式"
        >
          <Select>
            <Option value="emby">
              <Space>
                <FolderOutlined />
                Emby 风格 (推荐)
              </Space>
            </Option>
            <Option value="simple">
              <Space>
                <FileOutlined />
                简单风格 (兼容旧版)
              </Space>
            </Option>
          </Select>
        </Form.Item>

        <Divider />

        <Title level={5}>
          <InfoCircleOutlined style={{ marginRight: 8 }} />
          路径示例预览
        </Title>
        
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            {pathStyleExamples[currentStyle].map((example, index) => (
              <div key={index} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {example.icon}
                <Text strong>{example.type}:</Text>
                <Text code style={{ fontSize: '12px' }}>{example.path}</Text>
              </div>
            ))}
          </Space>
        </Card>

        {currentStyle === 'emby' && (
          <Alert
            type="info"
            showIcon
            message="Emby 风格优势"
            description={
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                <li>直观易懂的目录结构，便于手动管理</li>
                <li>按作品类型和季度自动分类组织</li>
                <li>文件名包含完整的剧集信息</li>
                <li>兼容 Emby、Jellyfin 等媒体服务器的命名规范</li>
                <li>自动处理特殊字符，确保跨平台兼容性</li>
              </ul>
            }
            style={{ marginBottom: 16 }}
          />
        )}

        {currentStyle === 'simple' && (
          <Alert
            type="warning"
            showIcon
            message="简单风格说明"
            description="使用数字ID作为目录和文件名，与旧版本保持兼容。适合不需要直观文件名的场景。"
            style={{ marginBottom: 16 }}
          />
        )}

        <Alert
          type="info"
          showIcon
          message="重要说明"
          description={
            <div>
              <Paragraph style={{ margin: 0 }}>
                • 修改此设置只影响新下载的弹幕文件，现有文件不会自动迁移
              </Paragraph>
              <Paragraph style={{ margin: 0 }}>
                • 建议在首次使用时设置，避免后续文件分散在不同目录
              </Paragraph>
              <Paragraph style={{ margin: 0 }}>
                • 重启服务后新设置才会生效
              </Paragraph>
            </div>
          }
          style={{ marginBottom: 24 }}
        />

        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={loading}>
              保存设置
            </Button>
            <Button
              icon={<SyncOutlined />}
              onClick={previewMigration}
              loading={migrationLoading}
            >
              迁移历史文件
            </Button>
          </Space>
        </Form.Item>
      </Form>

      {/* 迁移模态框 */}
      <Modal
        title="弹幕文件迁移"
        open={migrationModalVisible}
        onCancel={() => setMigrationModalVisible(false)}
        footer={[
          <Button key="cancel" onClick={() => setMigrationModalVisible(false)}>
            取消
          </Button>,
          <Button
            key="execute"
            type="primary"
            danger
            loading={migrationLoading}
            onClick={executeMigration}
            disabled={!migrationStats || migrationStats.files_to_migrate === 0}
          >
            执行迁移
          </Button>
        ]}
        width={800}
      >
        {migrationStats && (
          <div>
            <Alert
              type="warning"
              showIcon
              icon={<ExclamationCircleOutlined />}
              message="重要提醒"
              description="迁移操作将移动现有的弹幕文件到新的目录结构。建议先备份弹幕文件目录。"
              style={{ marginBottom: 16 }}
            />

            <Typography.Title level={5}>迁移统计</Typography.Title>
            <div style={{ marginBottom: 16 }}>
              <div>总分集数: {migrationStats.total_episodes}</div>
              <div>需要迁移的文件: {migrationStats.files_to_migrate}</div>
              <div>已是 Emby 风格: {migrationStats.files_already_emby_style}</div>
              <div>文件不存在: {migrationStats.files_not_found}</div>
            </div>

            {migrationStats.files_migrated > 0 && (
              <div style={{ marginBottom: 16 }}>
                <Progress
                  percent={Math.round((migrationStats.files_migrated / migrationStats.files_to_migrate) * 100)}
                  status={migrationStats.files_failed > 0 ? "exception" : "success"}
                />
                <div>已迁移: {migrationStats.files_migrated}</div>
                <div>失败: {migrationStats.files_failed}</div>
              </div>
            )}

            {migrationStats.errors.length > 0 && (
              <div>
                <Typography.Title level={5}>错误信息</Typography.Title>
                <div style={{ maxHeight: 200, overflow: 'auto', background: '#f5f5f5', padding: 8 }}>
                  {migrationStats.errors.map((error, index) => (
                    <div key={index} style={{ color: '#ff4d4f', fontSize: '12px' }}>
                      {error}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </Modal>
    </Card>
  )
}
