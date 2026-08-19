-- =========================================================
-- Supabase Schema for Website Scraper v2 (Multi-Category Taxonomy)
-- =========================================================

-- 1. Sites Table
CREATE TABLE IF NOT EXISTS sites (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    domain TEXT NOT NULL UNIQUE,
    name TEXT,
    openai_model TEXT DEFAULT 'gpt-5.4-nano',
    business_context TEXT,
    predefined_categories JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE sites ADD COLUMN IF NOT EXISTS openai_model TEXT DEFAULT 'gpt-5.4-nano';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS business_context TEXT;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS predefined_categories JSONB DEFAULT '[]'::jsonb;

-- 2. Categories Table (Business Pillars / Content Silos)
CREATE TABLE IF NOT EXISTS categories (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    site_id UUID REFERENCES sites(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT,
    summary TEXT, -- AI-generated synthesis of all offerings in this pillar
    target_audience TEXT,
    usps JSONB DEFAULT '[]'::jsonb,
    order_index INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(site_id, name)
);

-- 3. Pages Table
CREATE TABLE IF NOT EXISTS pages (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    site_id UUID REFERENCES sites(id) ON DELETE CASCADE,
    category_id UUID REFERENCES categories(id) ON DELETE SET NULL,
    url TEXT NOT NULL,
    path TEXT NOT NULL,
    title TEXT,
    meta_description TEXT,
    page_type TEXT,
    scrape_instructions TEXT,
    scraped_at TIMESTAMPTZ DEFAULT now(),
    status TEXT DEFAULT 'pending',
    raw_markdown TEXT,
    screenshot_url TEXT,
    UNIQUE(site_id, url)
);

ALTER TABLE pages ADD COLUMN IF NOT EXISTS category_id UUID REFERENCES categories(id) ON DELETE SET NULL;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS page_type TEXT;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS scrape_instructions TEXT;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS screenshot_url TEXT;

-- 4. Content Blocks Table
CREATE TABLE IF NOT EXISTS content_blocks (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    page_id UUID REFERENCES pages(id) ON DELETE CASCADE,
    category_id UUID REFERENCES categories(id) ON DELETE SET NULL,
    block_type TEXT NOT NULL,
    section_type TEXT,
    tag_name TEXT,
    content TEXT,
    attributes JSONB,
    hierarchy_level INTEGER NOT NULL DEFAULT 0,
    parent_block_id UUID REFERENCES content_blocks(id) ON DELETE CASCADE,
    order_index INTEGER NOT NULL,
    section_path TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE content_blocks ADD COLUMN IF NOT EXISTS category_id UUID REFERENCES categories(id) ON DELETE SET NULL;
ALTER TABLE content_blocks ADD COLUMN IF NOT EXISTS section_type TEXT;

-- 5. Images Table
CREATE TABLE IF NOT EXISTS images (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    page_id UUID REFERENCES pages(id) ON DELETE CASCADE,
    category_id UUID REFERENCES categories(id) ON DELETE SET NULL,
    block_id UUID REFERENCES content_blocks(id) ON DELETE SET NULL,
    original_url TEXT NOT NULL,
    storage_path TEXT,
    public_url TEXT,
    alt_text TEXT,
    image_type TEXT,
    width INTEGER,
    height INTEGER,
    file_size INTEGER,
    section_context TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE images ADD COLUMN IF NOT EXISTS category_id UUID REFERENCES categories(id) ON DELETE SET NULL;

-- 6. Navigation Table
CREATE TABLE IF NOT EXISTS navigation (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    site_id UUID REFERENCES sites(id) ON DELETE CASCADE,
    menu_type TEXT NOT NULL,
    items JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 7. Page Links Table
CREATE TABLE IF NOT EXISTS page_links (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    page_id UUID REFERENCES pages(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL,
    text TEXT,
    url TEXT NOT NULL,
    section_context TEXT,
    is_primary BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_categories_site_id ON categories(site_id);
CREATE INDEX IF NOT EXISTS idx_pages_site_id ON pages(site_id);
CREATE INDEX IF NOT EXISTS idx_pages_category_id ON pages(category_id);
CREATE INDEX IF NOT EXISTS idx_content_blocks_page_id ON content_blocks(page_id);
CREATE INDEX IF NOT EXISTS idx_content_blocks_category_id ON content_blocks(category_id);
CREATE INDEX IF NOT EXISTS idx_content_blocks_section_type ON content_blocks(section_type);
CREATE INDEX IF NOT EXISTS idx_images_page_id ON images(page_id);
CREATE INDEX IF NOT EXISTS idx_images_category_id ON images(category_id);
CREATE INDEX IF NOT EXISTS idx_navigation_site_id ON navigation(site_id);
CREATE INDEX IF NOT EXISTS idx_page_links_page_id ON page_links(page_id);
