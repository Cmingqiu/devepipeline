import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: '/projects',
    },
    {
      path: '/projects',
      name: 'projects',
      component: () => import('@/views/ProjectListView.vue'),
      meta: { title: '项目' },
    },
    {
      path: '/projects/:projectId/requirements',
      name: 'requirements',
      component: () => import('@/views/RequirementListView.vue'),
      meta: { title: '需求' },
    },
    {
      path: '/requirements/:requirementId',
      name: 'requirement-detail',
      component: () => import('@/views/RequirementDetailView.vue'),
      meta: { title: '需求详情' },
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFoundView.vue'),
      meta: { title: '页面不存在' },
    },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

const APP_NAME = 'DevPipeline'

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : ''
  document.title = title ? `${title} · ${APP_NAME}` : APP_NAME
})

export default router
