import { useTranslation } from 'react-i18next'
import { useState, useEffect, useCallback } from 'react'
import { X, UserPlus, Trash2, Search, Loader2, Users, Shield, ShieldCheck, User } from 'lucide-react'
import {
  listCollaborators,
  addCollaborator,
  removeCollaborator,
  CollaboratorMember
} from '../../api/annotation'
import { listUsersPaged, UserListItem } from '../../api/users'
import { useToast } from '../../contexts/ToastContext'
import { useAuth } from '../../contexts/AuthContext'

interface ShareAnnotationDialogProps {
  open: boolean
  onClose: () => void
  datasetId: string
}

export function ShareAnnotationDialog({ open, onClose, datasetId }: ShareAnnotationDialogProps) {
  const { t } = useTranslation()
  const toast = useToast()
  const { isAdmin } = useAuth()
  const [loading, setLoading] = useState(false)
  const [members, setMembers] = useState<CollaboratorMember[]>([])
  const [error, setError] = useState<string | null>(null)

  const [searchTerm, setSearchTerm] = useState('')
  const [searchResults, setSearchResults] = useState<UserListItem[]>([])
  const [searching, setSearching] = useState(false)
  const [addingUser, setAddingUser] = useState<string | null>(null)

  const [pendingRemoveUser, setPendingRemoveUser] = useState<string | null>(null)
  const [removingUser, setRemovingUser] = useState<string | null>(null)

  const loadCollaborators = useCallback(async () => {
    if (!datasetId) return
    setLoading(true)
    setError(null)
    try {
      const res = await listCollaborators(datasetId)
      setMembers(res.members)
    } catch (err) {
      console.error(err)
      setError(t('annotation.collab.dialog.loadError'))
    } finally {
      setLoading(false)
    }
  }, [datasetId, t])

  useEffect(() => {
    if (open) {
      loadCollaborators()
      setSearchTerm('')
      setSearchResults([])
      setPendingRemoveUser(null)
    }
  }, [open, loadCollaborators])

  useEffect(() => {
    const timer = setTimeout(async () => {
      if (!searchTerm.trim()) {
        setSearchResults([])
        return
      }

      setSearching(true)
      try {
        const res = await listUsersPaged({
          search: searchTerm,
          exclude_admin: false,
          page: 1,
          page_size: 10
        })
        
        const existingIds = new Set(members.map(m => m.user_id))
        setSearchResults(res.items.filter(u => !existingIds.has(u.id)))
      } catch (err) {
        console.error(err)
      } finally {
        setSearching(false)
      }
    }, 300)

    return () => clearTimeout(timer)
  }, [searchTerm, members])

  const handleAddCollaborator = async (user: UserListItem) => {
    setAddingUser(user.id)
    try {
      await addCollaborator(datasetId, user.id)
      await loadCollaborators()
      setSearchTerm('')
      setSearchResults([])
    } catch (err) {
      console.error(err)
    } finally {
      setAddingUser(null)
    }
  }

  const handleRemoveConfirm = async (member: CollaboratorMember) => {
    setPendingRemoveUser(null)
    setRemovingUser(member.user_id)
    try {
      const res = await removeCollaborator(datasetId, member.user_id)
      if (res.residual_region_count > 0) {
        toast.success(t('annotation.collab.dialog.removedWithRegions', { count: res.residual_region_count }))
      }
      await loadCollaborators()
    } catch (err) {
      console.error(err)
      toast.error(t('annotation.collab.dialog.removeFailed'))
    } finally {
      setRemovingUser(null)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[200] p-4 animate-in fade-in duration-200">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg overflow-hidden flex flex-col max-h-[80vh]">
        <div className="px-6 py-4 border-b flex items-center justify-between bg-gray-50">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-indigo-100 rounded-lg text-indigo-600">
              <Users className="w-5 h-5" />
            </div>
            <h2 className="text-lg font-semibold text-gray-900">{t('annotation.collab.dialog.title')}</h2>
          </div>
          <button  
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors p-1 hover:bg-gray-100 rounded-lg"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          <div className="mb-8">
            <label htmlFor="collaborator-search" className="block text-sm font-medium text-gray-700 mb-2">{t('annotation.collab.dialog.addCollaborator')}</label>
            <div className="relative">
              <Search className="absolute left-3 top-2.5 w-4 h-4 text-gray-400" />
              <input
                id="collaborator-search"
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder={t('annotation.collab.dialog.searchPlaceholder')}
                className="w-full pl-9 pr-4 py-2 text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none transition-all"
              />
              {searching && (
                <div className="absolute right-3 top-2.5">
                  <Loader2 className="w-4 h-4 animate-spin text-indigo-500" />
                </div>
              )}
            </div>

            {searchTerm && !searching && (
              <div className="mt-2 bg-white border border-gray-100 rounded-lg shadow-lg overflow-hidden divide-y divide-gray-50">
                {searchResults.length > 0 ? (
                  searchResults.map(user => (
                    <div key={user.id} className="flex items-center justify-between p-3 hover:bg-gray-50 transition-colors">
                      <div className="flex items-center gap-3 overflow-hidden">
                        <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-600 flex-shrink-0">
                          <span className="text-xs font-bold">
                            {(user.nickname || user.email || '?').substring(0, 2).toUpperCase()}
                          </span>
                        </div>
                        <div className="flex flex-col min-w-0">
                          <span className="text-sm font-medium text-gray-900 truncate">
                            {user.nickname || user.email}
                          </span>
                          {user.email && (
                            <span className="text-xs text-gray-500 truncate">{user.email}</span>
                          )}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleAddCollaborator(user)}
                        disabled={addingUser === user.id}
                        className="p-1.5 text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors disabled:opacity-50"
                      >
                        {addingUser === user.id ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <UserPlus className="w-4 h-4" />
                        )}
                      </button>
                    </div>
                  ))
                ) : (
                  <div className="p-4 text-center text-sm text-gray-500">
                    {t('annotation.collab.dialog.noResults')}
                  </div>
                )}
              </div>
            )}
          </div>

          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-3 flex items-center gap-2">
              {t('annotation.collab.dialog.currentMembers')}
              <span className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded-full text-xs">
                {members.length}
              </span>
            </h3>

            {loading ? (
              <div className="flex justify-center py-8">
                <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
              </div>
            ) : error ? (
              <div className="p-4 bg-red-50 text-red-600 text-sm rounded-lg text-center">
                {error}
              </div>
            ) : (
              <div className="space-y-3">
                {(isAdmin ? members : members.filter(m => m.role !== 'implicit_admin')).map(member => (
                  <div key={member.user_id} className="flex items-center justify-between p-3 bg-gray-50 rounded-xl border border-gray-100">
                    <div className="flex items-center gap-3 overflow-hidden">
                      <div className="w-9 h-9 rounded-full bg-white border border-gray-200 flex items-center justify-center text-gray-500 shadow-sm flex-shrink-0">
                        {member.role === 'owner' ? (
                          <ShieldCheck className="w-4 h-4 text-blue-500" />
                        ) : member.role === 'implicit_admin' ? (
                          <Shield className="w-4 h-4 text-purple-500" />
                        ) : (
                          <User className="w-4 h-4" />
                        )}
                      </div>
                      <div className="flex flex-col min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-gray-900 truncate">
                            {member.nickname || 'Unknown User'}
                          </span>
                          {member.role === 'owner' && (
                            <span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 text-[10px] font-medium rounded">
                              {t('annotation.collab.dialog.ownerRole')}
                            </span>
                          )}
                          {member.role === 'implicit_admin' && (
                            <span className="px-1.5 py-0.5 bg-purple-100 text-purple-700 text-[10px] font-medium rounded">
                              {t('annotation.collab.dialog.adminRole')}
                            </span>
                          )}
                          {member.role === 'collaborator' && (
                            <span className="px-1.5 py-0.5 bg-gray-200 text-gray-600 text-[10px] font-medium rounded">
                              {t('annotation.collab.dialog.collaboratorRole')}
                            </span>
                          )}
                        </div>
                        {member.email && (
                          <span className="text-xs text-gray-500 truncate">{member.email}</span>
                        )}
                      </div>
                    </div>

                    {member.role === 'collaborator' && (
                      removingUser === member.user_id ? (
                        <Loader2 className="w-4 h-4 animate-spin text-gray-400 flex-shrink-0" />
                      ) : pendingRemoveUser === member.user_id ? (
                        <div className="flex items-center gap-1.5 flex-shrink-0">
                          <span className="text-xs text-gray-500">{t('annotation.collab.dialog.removeConfirm')}</span>
                          <button
                            type="button"
                            onClick={() => setPendingRemoveUser(null)}
                            className="px-2 py-1 text-xs text-gray-600 bg-white border border-gray-200 rounded-md hover:bg-gray-50 transition-colors"
                          >
                            {t('common.cancel')}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleRemoveConfirm(member)}
                            className="px-2 py-1 text-xs text-white bg-red-600 rounded-md hover:bg-red-700 transition-colors"
                          >
                            {t('common.confirm')}
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setPendingRemoveUser(member.user_id)}
                          className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                          title={t('annotation.collab.dialog.removeCollaborator')}
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      )
                    )}
                  </div>
                ))}

                {members.length === 0 && (
                  <div className="text-center py-8 text-gray-400 text-sm">
                    {t('annotation.collab.dialog.noMembers')}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="px-6 py-4 bg-gray-50 border-t text-xs text-gray-500 text-center">
          {t('annotation.collab.dialog.footerHint')}
        </div>
      </div>
    </div>
  )
}
